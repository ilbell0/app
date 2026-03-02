from fastapi import FastAPI, APIRouter, HTTPException, Response, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import httpx
from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Emergent LLM Key
EMERGENT_LLM_KEY = os.getenv('EMERGENT_LLM_KEY', '')

# Create the main app
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserSession(BaseModel):
    user_id: str
    session_token: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SessionRequest(BaseModel):
    session_id: str

class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    role: str  # 'user' or 'assistant'
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ChatRequest(BaseModel):
    message: str
    language: str = 'en'  # 'en' or 'it'

class FavoriteTactic(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    formation_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# ==================== AUTH HELPER ====================

async def get_current_user(request: Request) -> User:
    """Get current user from session token (cookie or Authorization header)"""
    # Try cookie first
    session_token = request.cookies.get('session_token')
    
    # Fallback to Authorization header
    if not session_token:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            session_token = auth_header[7:]
    
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session_doc = await db.user_sessions.find_one(
        {"session_token": session_token},
        {"_id": 0}
    )
    
    if not session_doc:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Check expiry
    expires_at = session_doc["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expired")
    
    # Get user
    user_doc = await db.users.find_one(
        {"user_id": session_doc["user_id"]},
        {"_id": 0}
    )
    
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found")
    
    return User(**user_doc)

# ==================== AUTH ENDPOINTS ====================

@api_router.post("/auth/session")
async def create_session(request: SessionRequest, response: Response):
    """Exchange session_id from Emergent Auth for a session token"""
    try:
        # Call Emergent Auth to get user data
        async with httpx.AsyncClient() as client:
            auth_response = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": request.session_id}
            )
            
            if auth_response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid session ID")
            
            auth_data = auth_response.json()
        
        # Check if user exists
        existing_user = await db.users.find_one(
            {"email": auth_data["email"]},
            {"_id": 0}
        )
        
        if existing_user:
            user_id = existing_user["user_id"]
            # Update user info
            await db.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "name": auth_data["name"],
                    "picture": auth_data.get("picture")
                }}
            )
        else:
            # Create new user
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            new_user = {
                "user_id": user_id,
                "email": auth_data["email"],
                "name": auth_data["name"],
                "picture": auth_data.get("picture"),
                "created_at": datetime.now(timezone.utc)
            }
            await db.users.insert_one(new_user)
        
        # Create session
        session_token = auth_data.get("session_token", f"session_{uuid.uuid4().hex}")
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        
        # Delete old sessions for this user
        await db.user_sessions.delete_many({"user_id": user_id})
        
        # Create new session
        session = {
            "user_id": user_id,
            "session_token": session_token,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc)
        }
        await db.user_sessions.insert_one(session)
        
        # Set cookie
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="none",
            path="/",
            max_age=7 * 24 * 60 * 60  # 7 days
        )
        
        # Get user data
        user_doc = await db.users.find_one(
            {"user_id": user_id},
            {"_id": 0}
        )
        
        return {"user": user_doc, "session_token": session_token}
        
    except httpx.HTTPError as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=500, detail="Authentication service error")

@api_router.get("/auth/me")
async def get_me(request: Request):
    """Get current authenticated user"""
    user = await get_current_user(request)
    return user.model_dump()

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    """Logout and clear session"""
    session_token = request.cookies.get('session_token')
    if session_token:
        await db.user_sessions.delete_many({"session_token": session_token})
    
    response.delete_cookie(
        key="session_token",
        path="/",
        secure=True,
        samesite="none"
    )
    
    return {"message": "Logged out successfully"}

# ==================== FORMATIONS DATA (EXPANDED) ====================

FORMATIONS = [
    {
        "id": "442",
        "name": "4-4-2 Classic",
        "description_en": "Classic balanced formation. Strong in both defense and attack with 4 defenders, 4 midfielders, and 2 strikers. One of the oldest and most reliable formations in football.",
        "description_it": "Formazione classica ed equilibrata. Forte sia in difesa che in attacco con 4 difensori, 4 centrocampisti e 2 attaccanti. Una delle formazioni più antiche e affidabili nel calcio.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST", "ST"],
        "strengths_en": ["Balanced", "Good width", "Partnership up front", "Simple to execute"],
        "strengths_it": ["Equilibrata", "Buona ampiezza", "Partnership in attacco", "Semplice da eseguire"],
        "weaknesses_en": ["Can be outnumbered in midfield", "Requires fit wingers"],
        "weaknesses_it": ["Può essere superata numericamente a centrocampo", "Richiede ali in forma"],
        "tactic_type_en": "Balanced",
        "tactic_type_it": "Bilanciato",
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Stay compact and let them come. Use long balls to your strikers on counter.",
                "tip_it": "Resta compatto e lasciali venire. Usa palle lunghe agli attaccanti in contropiede."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Play your natural game. Use width and crosses to find your two strikers.",
                "tip_it": "Gioca il tuo gioco naturale. Usa l'ampiezza e i cross per trovare i due attaccanti."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Dominate with high pressing and quick passing. Overwhelm their defense with numbers.",
                "tip_it": "Domina con pressing alto e passaggi veloci. Travolgi la loro difesa con i numeri."
            }
        }
    },
    {
        "id": "433",
        "name": "4-3-3",
        "description_en": "Attacking formation with 3 forwards. Great for possession and pressing high up the pitch. Dominates the flanks with wingers.",
        "description_it": "Formazione offensiva con 3 attaccanti. Ottima per il possesso palla e il pressing alto. Domina le fasce con le ali.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "MC", "AML", "ST", "AMR"],
        "strengths_en": ["High pressing", "Width in attack", "Creative midfield", "Overloads flanks"],
        "strengths_it": ["Pressing alto", "Ampiezza in attacco", "Centrocampo creativo", "Sovraccarica le fasce"],
        "weaknesses_en": ["Vulnerable to counters", "Midfield can be overrun", "Weak central defense"],
        "weaknesses_it": ["Vulnerabile ai contropiedi", "Centrocampo può essere sopraffatto", "Difesa centrale debole"],
        "tactic_type_en": "High Press / Possession",
        "tactic_type_it": "Pressing Alto / Possesso",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Hard",
            "marking": "Man-to-Man",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Don't overcommit. Use wingers to stretch their defense and exploit space on counters.",
                "tip_it": "Non esporti troppo. Usa le ali per allargare la difesa e sfrutta gli spazi in contropiede."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Press high and dominate flanks. Your wingers are the key to breaking them down.",
                "tip_it": "Pressa alto e domina le fasce. Le tue ali sono la chiave per sfondare."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Ultra Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Full attack mode! Press relentlessly and overload their half. Goals will come.",
                "tip_it": "Attacco totale! Pressa senza sosta e sovraccarica la loro metà campo. I gol arriveranno."
            }
        }
    },
    {
        "id": "352",
        "name": "3-5-2",
        "description_en": "Midfield-dominant formation with wing-backs. Controls the center of the pitch with 5 midfielders.",
        "description_it": "Formazione dominante a centrocampo con esterni. Controlla il centro del campo con 5 centrocampisti.",
        "positions": ["GK", "DC", "DC", "DC", "ML", "MC", "MC", "MC", "MR", "ST", "ST"],
        "strengths_en": ["Midfield control", "Numerical advantage in center", "Partnership up front"],
        "strengths_it": ["Controllo del centrocampo", "Vantaggio numerico al centro", "Partnership in attacco"],
        "weaknesses_en": ["Exposed flanks", "Requires versatile wing-backs", "Weak against wide formations"],
        "weaknesses_it": ["Fianchi esposti", "Richiede esterni versatili", "Debole contro formazioni ampie"],
        "tactic_type_en": "Possession / Control",
        "tactic_type_it": "Possesso / Controllo",
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Protect your 3 CBs. Wing-backs must stay deep. Hit them with long balls to strikers.",
                "tip_it": "Proteggi i 3 DC. Gli esterni devono restare bassi. Colpisci con palle lunghe agli attaccanti."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Control midfield with your 5-man setup. Let wing-backs overlap when safe.",
                "tip_it": "Controlla il centrocampo con i 5 giocatori. Lascia sovrapporre gli esterni quando è sicuro."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Dominate center and use wing-backs as extra attackers. Overwhelm them!",
                "tip_it": "Domina il centro e usa gli esterni come attaccanti aggiuntivi. Travolgili!"
            }
        }
    },
    {
        "id": "4231",
        "name": "4-2-3-1",
        "description_en": "Modern tactical formation with double pivot and attacking midfielder. Great balance between defense and attack.",
        "description_it": "Formazione tattica moderna con doppio pivot e trequartista. Grande equilibrio tra difesa e attacco.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "DMC", "AML", "AMC", "AMR", "ST"],
        "strengths_en": ["Defensive stability", "Creative playmaker", "Compact midfield", "Flexible"],
        "strengths_it": ["Stabilità difensiva", "Regista creativo", "Centrocampo compatto", "Flessibile"],
        "weaknesses_en": ["Lone striker isolated", "Depends heavily on #10", "Can lack width"],
        "weaknesses_it": ["Attaccante solitario isolato", "Dipende molto dal trequartista", "Può mancare ampiezza"],
        "tactic_type_en": "Balanced / Counter-Attack",
        "tactic_type_it": "Bilanciato / Contropiede",
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Double pivot protects defense. Use AMC to link play on counter-attacks.",
                "tip_it": "Il doppio pivot protegge la difesa. Usa il trequartista per collegare in contropiede."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Let your AMC dictate play. Use AML/AMR width to create for the lone striker.",
                "tip_it": "Lascia che il trequartista diriga il gioco. Usa AML/AMR per creare per l'attaccante."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Push your AML/AMR high. Overload their defense with creative play through AMC.",
                "tip_it": "Spingi AML/AMR in avanti. Sovraccarica la difesa con gioco creativo dal trequartista."
            }
        }
    },
    {
        "id": "451v",
        "name": "4-5-1 V-Style",
        "description_en": "Defensive V-shaped formation. DMC anchors the midfield with AMC providing creativity. Best for counter-attacking against stronger opponents.",
        "description_it": "Formazione difensiva a V. Il DMC ancora il centrocampo con l'AMC che fornisce creatività. Ideale per contropiede contro avversari più forti.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MC", "MC", "AML", "AMR", "ST"],
        "strengths_en": ["Defensive solidity", "Midfield dominance", "Counter-attack potential", "Flexible wings"],
        "strengths_it": ["Solidità difensiva", "Dominio a centrocampo", "Potenziale di contropiede", "Ali flessibili"],
        "weaknesses_en": ["Lone striker", "Limited attacking options", "Needs fast wingers"],
        "weaknesses_it": ["Attaccante solitario", "Opzioni offensive limitate", "Richiede ali veloci"],
        "tactic_type_en": "Counter-Attack / Defensive",
        "tactic_type_it": "Contropiede / Difensivo",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Ultra Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Park the bus! Stay deep and hit them hard on counters with fast wingers.",
                "tip_it": "Catenaccio! Resta arretrato e colpisci forte in contropiede con ali veloci."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Control game through midfield. Use width to find space for your lone striker.",
                "tip_it": "Controlla la partita dal centrocampo. Usa l'ampiezza per trovare spazio per l'attaccante."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Push up and dominate midfield. Your 5-man midfield should overwhelm theirs.",
                "tip_it": "Spingi e domina il centrocampo. I tuoi 5 centrocampisti devono sopraffare i loro."
            }
        }
    },
    {
        "id": "41212nd",
        "name": "4-1-2-1-2 Narrow Diamond",
        "description_en": "Diamond midfield formation. Strong through the center with DMC protecting defense and AMC linking play. Great for controlling possession.",
        "description_it": "Formazione con diamante a centrocampo. Forte al centro con DMC che protegge la difesa e AMC che collega il gioco. Ottima per controllare il possesso.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MC", "MC", "AMC", "ST", "ST"],
        "strengths_en": ["Central dominance", "Creative #10", "Two striker partnership", "Good passing lanes"],
        "strengths_it": ["Dominio centrale", "Trequartista creativo", "Partnership di due attaccanti", "Buone linee di passaggio"],
        "weaknesses_en": ["No natural wingers", "Exposed flanks", "Requires box-to-box midfielders"],
        "weaknesses_it": ["Nessuna ala naturale", "Fianchi esposti", "Richiede centrocampisti box-to-box"],
        "tactic_type_en": "Possession / Central Attack",
        "tactic_type_it": "Possesso / Attacco Centrale",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "DMC shields the back 4. Long balls to striker partnership on counters.",
                "tip_it": "Il DMC protegge la difesa a 4. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Control the center and let AMC create for the 2 strikers. Be patient.",
                "tip_it": "Controlla il centro e lascia che l'AMC crei per i 2 attaccanti. Sii paziente."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Dominate the center completely. Your AMC should feast on their weak midfield.",
                "tip_it": "Domina il centro completamente. Il tuo AMC deve banchettare sul loro centrocampo debole."
            }
        }
    },
    {
        "id": "343",
        "name": "3-4-3",
        "description_en": "Ultra-attacking formation. High risk, high reward with 3 defenders and 3 forwards. Best used when chasing a game.",
        "description_it": "Formazione ultra-offensiva. Alto rischio, alta ricompensa con 3 difensori e 3 attaccanti. Da usare quando si insegue il risultato.",
        "positions": ["GK", "DC", "DC", "DC", "MR", "MC", "MC", "ML", "AML", "ST", "AMR"],
        "strengths_en": ["Attacking firepower", "Width", "Pressing intensity", "Overwhelming offense"],
        "strengths_it": ["Potenza offensiva", "Ampiezza", "Intensità del pressing", "Attacco travolgente"],
        "weaknesses_en": ["Defensively weak", "Exposed to counters", "Requires stamina"],
        "weaknesses_it": ["Difensivamente debole", "Esposta ai contropiedi", "Richiede resistenza"],
        "tactic_type_en": "All-Out Attack",
        "tactic_type_it": "Attacco Totale",
        "recommended_tactics": {
            "mentality": "Hard Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Hard",
            "marking": "Man-to-Man",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "RISKY! Use only if behind. Try to score early and protect the 3 CBs.",
                "tip_it": "RISCHIOSO! Usa solo se sei in svantaggio. Prova a segnare presto e proteggi i 3 DC."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Attack is the best defense. Use width and press high to force errors.",
                "tip_it": "L'attacco è la miglior difesa. Usa l'ampiezza e pressa alto per forzare errori."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Ultra Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Destroy them! Full attack mode with relentless pressing. Score as many as you can!",
                "tip_it": "Distruggili! Attacco totale con pressing senza sosta. Segna più gol possibili!"
            }
        }
    },
    {
        "id": "541",
        "name": "5-4-1",
        "description_en": "Parking the bus formation. Maximum defensive solidity with 5 at the back. Perfect for protecting a lead.",
        "description_it": "Formazione catenaccio. Massima solidità difensiva con 5 in difesa. Perfetta per proteggere un vantaggio.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST"],
        "strengths_en": ["Maximum defense", "Hard to break down", "Ideal for protecting leads", "Counter-attack ready"],
        "strengths_it": ["Massima difesa", "Difficile da penetrare", "Ideale per proteggere vantaggi", "Pronta al contropiede"],
        "weaknesses_en": ["Very limited attack", "Requires discipline", "Can invite pressure"],
        "weaknesses_it": ["Attacco molto limitato", "Richiede disciplina", "Può invitare la pressione"],
        "tactic_type_en": "Ultra Defensive / Bus Parking",
        "tactic_type_it": "Ultra Difensivo / Catenaccio",
        "recommended_tactics": {
            "mentality": "Hard Defending",
            "focus_passing": "Mixed",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Ultra Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Full catenaccio! 5-4-1 deep and compact. Long balls to lone striker on rare counters.",
                "tip_it": "Catenaccio totale! 5-4-1 profondo e compatto. Palle lunghe all'attaccante nei rari contropiedi."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Stay organized. Let wing-backs push when safe. Target lone striker on transitions.",
                "tip_it": "Resta organizzato. Lascia sovrapporre gli esterni quando è sicuro. Punta sull'attaccante nelle transizioni."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Push wing-backs higher to create. You can afford to be more adventurous.",
                "tip_it": "Spingi gli esterni più in alto per creare. Puoi permetterti di essere più avventuroso."
            }
        }
    },
    {
        "id": "4141",
        "name": "4-1-4-1",
        "description_en": "Single pivot formation. DMC acts as shield for defense while 4 midfielders provide width and creativity.",
        "description_it": "Formazione con singolo pivot. Il DMC funge da scudo per la difesa mentre 4 centrocampisti forniscono ampiezza e creatività.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MR", "MC", "MC", "ML", "ST"],
        "strengths_en": ["Defensive shield", "Wide midfield", "Balanced structure", "Flexible"],
        "strengths_it": ["Scudo difensivo", "Centrocampo ampio", "Struttura equilibrata", "Flessibile"],
        "weaknesses_en": ["Lone striker", "Pivot can be overloaded", "Needs quality DMC"],
        "weaknesses_it": ["Attaccante solitario", "Pivot può essere sovraccaricato", "Richiede DMC di qualità"],
        "tactic_type_en": "Balanced / Defensive",
        "tactic_type_it": "Bilanciato / Difensivo",
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Mixed",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "DMC protects the back 4. Use width on counters to find the lone striker.",
                "tip_it": "Il DMC protegge la difesa a 4. Usa l'ampiezza nei contropiedi per trovare l'attaccante."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Balanced approach. Use the width of ML/MR to stretch their defense.",
                "tip_it": "Approccio bilanciato. Usa l'ampiezza di ML/MR per allargare la loro difesa."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Push wide midfielders high. DMC provides cover while you dominate their half.",
                "tip_it": "Spingi gli esterni alti. Il DMC copre mentre dominate la loro metà campo."
            }
        }
    },
    {
        "id": "4222",
        "name": "4-2-2-2 Hexagon",
        "description_en": "Compact formation with two defensive mids and two attacking mids. Creates numerical advantage in the center.",
        "description_it": "Formazione compatta con due centrocampisti difensivi e due offensivi. Crea vantaggio numerico al centro.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "AML", "AMR", "ST", "ST"],
        "strengths_en": ["Central control", "Two partnerships", "Compact shape", "Transitions well"],
        "strengths_it": ["Controllo centrale", "Due partnership", "Forma compatta", "Buone transizioni"],
        "weaknesses_en": ["Lacks width", "No natural wingers", "Predictable"],
        "weaknesses_it": ["Manca ampiezza", "Nessuna ala naturale", "Prevedibile"],
        "tactic_type_en": "Central / Transition",
        "tactic_type_it": "Centrale / Transizione",
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Stay compact in center. Use the 2 striker partnership to hold the ball on counters.",
                "tip_it": "Resta compatto al centro. Usa la coppia d'attacco per tenere palla nei contropiedi."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Control center with your compact shape. AML/AMR should drift in to support strikers.",
                "tip_it": "Controlla il centro con la forma compatta. AML/AMR devono accentrarsi per supportare gli attaccanti."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Overwhelm center! Your 4 central attackers should dominate their midfield.",
                "tip_it": "Travolgi il centro! I tuoi 4 attaccanti centrali devono dominare il loro centrocampo."
            }
        }
    },
    {
        "id": "3142",
        "name": "3-1-4-2",
        "description_en": "Midfield-heavy formation with DMC anchor. 4 midfielders dominate the center while 2 strikers wait for service.",
        "description_it": "Formazione pesante a centrocampo con DMC come ancora. 4 centrocampisti dominano il centro mentre 2 attaccanti aspettano il servizio.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "ML", "MC", "MC", "MR", "ST", "ST"],
        "strengths_en": ["Midfield dominance", "Two strikers", "Flexible width", "Counter-attack ready"],
        "strengths_it": ["Dominio a centrocampo", "Due attaccanti", "Ampiezza flessibile", "Pronta al contropiede"],
        "weaknesses_en": ["Exposed defense", "Wing-backs must track back", "High stamina required"],
        "weaknesses_it": ["Difesa esposta", "Esterni devono rientrare", "Richiede alta resistenza"],
        "tactic_type_en": "Counter-Attack / Midfield Control",
        "tactic_type_it": "Contropiede / Controllo Centrocampo",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Mixed",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Man-to-Man",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "DMC protects the 3 CBs. Wing-mids stay back. Long balls to striker duo on counters.",
                "tip_it": "Il DMC protegge i 3 DC. Gli esterni restano bassi. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Dominate midfield. Let ML/MR overlap to create for the strikers.",
                "tip_it": "Domina il centrocampo. Lascia sovrapporre ML/MR per creare per gli attaccanti."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Press high and overwhelm. Wing-mids become attacking wingers!",
                "tip_it": "Pressa alto e travolgi. Gli esterni diventano ali d'attacco!"
            }
        }
    },
    {
        "id": "4312",
        "name": "4-3-1-2",
        "description_en": "Italian formation with trequartista behind two strikers. Strong through the center with creative playmaker.",
        "description_it": "Formazione italiana con trequartista dietro due attaccanti. Forte al centro con regista creativo.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "MC", "AMC", "ST", "ST"],
        "strengths_en": ["Creative #10", "Two striker partnership", "Midfield control", "Italian style"],
        "strengths_it": ["Trequartista creativo", "Partnership di attaccanti", "Controllo centrocampo", "Stile italiano"],
        "weaknesses_en": ["No width", "Relies on AMC", "Flanks exposed"],
        "weaknesses_it": ["Nessuna ampiezza", "Dipende dall'AMC", "Fianchi esposti"],
        "tactic_type_en": "Possession / Creative Attack",
        "tactic_type_it": "Possesso / Attacco Creativo",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Protect the 3 MCs. Use AMC to link play on counters to the 2 strikers.",
                "tip_it": "Proteggi i 3 MC. Usa l'AMC per collegare in contropiede verso i 2 attaccanti."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Let AMC orchestrate attacks. Patient buildup through center to the strikers.",
                "tip_it": "Lascia l'AMC orchestrare gli attacchi. Costruzione paziente dal centro verso gli attaccanti."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "AMC runs the show! Feed the 2 strikers constantly. They can't handle it.",
                "tip_it": "L'AMC comanda il gioco! Servi costantemente i 2 attaccanti. Non potranno reggere."
            }
        }
    },
    {
        "id": "532",
        "name": "5-3-2",
        "description_en": "Defensive formation with wing-backs providing width. 3 central defenders ensure solidity at the back.",
        "description_it": "Formazione difensiva con esterni che forniscono ampiezza. 3 difensori centrali garantiscono solidità dietro.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "MC", "MC", "MC", "ST", "ST"],
        "strengths_en": ["Defensive solidity", "Wing-back runs", "Two strikers", "Hard to break"],
        "strengths_it": ["Solidità difensiva", "Sovrapposizioni degli esterni", "Due attaccanti", "Difficile da sfondare"],
        "weaknesses_en": ["Can be too defensive", "Wing-backs tire easily", "Lacks midfield creativity"],
        "weaknesses_it": ["Può essere troppo difensiva", "Esterni si stancano facilmente", "Manca creatività a centrocampo"],
        "tactic_type_en": "Defensive / Counter-Attack",
        "tactic_type_it": "Difensivo / Contropiede",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Ultra Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "5 defenders tight and compact. Wing-backs stay back. Counter through strikers.",
                "tip_it": "5 difensori stretti e compatti. Gli esterni restano bassi. Contropiede tramite gli attaccanti."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Solid defense first. Let wing-backs overlap when safe to create for strikers.",
                "tip_it": "Prima difesa solida. Lascia sovrapporre gli esterni quando è sicuro per creare per gli attaccanti."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Wing-backs push high as extra attackers. Overwhelm with numbers on flanks.",
                "tip_it": "Gli esterni spingono in alto come attaccanti extra. Travolgi con i numeri sulle fasce."
            }
        }
    },
    {
        "id": "31231",
        "name": "3-1-2-3-1",
        "description_en": "Modern attacking formation popular in 2025. DMC anchors defense while 3 attacking midfielders provide creativity.",
        "description_it": "Formazione offensiva moderna popolare nel 2025. Il DMC ancora la difesa mentre 3 trequartisti forniscono creatività.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "MC", "MC", "AML", "AMC", "AMR", "ST"],
        "strengths_en": ["Creative front line", "Midfield dominance", "Flexible attack", "Pressing options"],
        "strengths_it": ["Linea offensiva creativa", "Dominio a centrocampo", "Attacco flessibile", "Opzioni di pressing"],
        "weaknesses_en": ["Three at the back risk", "Needs fast CBs", "Can concede counters"],
        "weaknesses_it": ["Rischio con tre difensori", "Richiede DC veloci", "Può subire contropiedi"],
        "tactic_type_en": "Attacking / High Press",
        "tactic_type_it": "Offensivo / Pressing Alto",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Mixed",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Be careful with 3 at back! DMC must protect well. Hit them on quick transitions.",
                "tip_it": "Attento con 3 in difesa! Il DMC deve proteggere bene. Colpisci nelle transizioni veloci."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Use your 3 AMs to dominate. Press high and create overloads in attack.",
                "tip_it": "Usa i 3 trequartisti per dominare. Pressa alto e crea superiorità numerica in attacco."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Ultra Offensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Unleash all 3 AMs! Total dominance in their half. Score many goals!",
                "tip_it": "Scatena tutti e 3 i trequartisti! Dominio totale nella loro metà campo. Segna tanti gol!"
            }
        }
    },
    # ==================== NEW 2025/2026 META FORMATIONS ====================
    {
        "id": "31411",
        "name": "3-1-4-1-1",
        "description_en": "2025/2026 META formation. Dominant midfield with 7 players in the center. DMC shields 3 CBs while AMC creates for lone striker. Most popular formation for winning quadruples.",
        "description_it": "Formazione META 2025/2026. Centrocampo dominante con 7 giocatori al centro. Il DMC protegge i 3 DC mentre l'AMC crea per l'attaccante solitario. Formazione più popolare per vincere quadruple.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "ML", "MC", "MC", "MR", "AMC", "ST"],
        "strengths_en": ["Midfield dominance (7 players)", "DMC protection", "Creative AMC", "Versatile width with ML/MR", "Strong vs balanced formations"],
        "strengths_it": ["Dominio centrocampo (7 giocatori)", "Protezione DMC", "AMC creativo", "Ampiezza versatile con ML/MR", "Forte contro formazioni bilanciate"],
        "weaknesses_en": ["Vulnerable on flanks", "Only 3 CBs", "Needs quality AMC", "Can be overrun by wide formations"],
        "weaknesses_it": ["Vulnerabile sulle fasce", "Solo 3 DC", "Richiede AMC di qualità", "Può essere sopraffatta da formazioni ampie"],
        "tactic_type_en": "Midfield Control / META 2026",
        "tactic_type_it": "Controllo Centrocampo / META 2026",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Mixed",
            "passing_style": "Mixed",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Ultra Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "DMC backward arrow essential! Let them attack and counter through AMC to ST. Stay compact.",
                "tip_it": "Freccia in basso sul DMC essenziale! Lasciali attaccare e contropiede tramite AMC verso ST. Resta compatto."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Control midfield with 7 players. AMC dictates play. ML/MR stretch defense for ST.",
                "tip_it": "Controlla il centrocampo con 7 giocatori. L'AMC dirige il gioco. ML/MR allargano la difesa per ST."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Full dominance! Push MC up with arrow. AMC + ST combo will destroy their defense.",
                "tip_it": "Dominio totale! Spingi MC in alto con freccia. Il duo AMC + ST distruggerà la loro difesa."
            }
        }
    },
    {
        "id": "4123",
        "name": "4-1-2-3",
        "description_en": "Modern attacking formation with False Nine potential. DMC provides cover while 3 forwards overwhelm opposition defense. Popular in 2025/2026 meta.",
        "description_it": "Formazione offensiva moderna con potenziale Falso Nove. Il DMC fornisce copertura mentre 3 attaccanti travolgono la difesa avversaria. Popolare nel meta 2025/2026.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MC", "MC", "AML", "ST", "AMR"],
        "strengths_en": ["Three forwards", "False Nine option", "Strong wing play", "DMC shield", "Fast transitions"],
        "strengths_it": ["Tre attaccanti", "Opzione Falso Nove", "Gioco sulle fasce forte", "Scudo DMC", "Transizioni veloci"],
        "weaknesses_en": ["Can be overrun in midfield", "Needs quality wingers", "Vulnerable to 5-man midfields"],
        "weaknesses_it": ["Può essere sopraffatto a centrocampo", "Richiede ali di qualità", "Vulnerabile a centrocampi a 5"],
        "tactic_type_en": "Attacking / Wide Play",
        "tactic_type_it": "Offensivo / Gioco Ampio",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Use AML/AMR pace on counters. Long balls to wings, then cross to ST.",
                "tip_it": "Usa la velocità di AML/AMR in contropiede. Palle lunghe sulle fasce, poi cross per ST."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Dominate flanks with your 3 attackers. Press high and force mistakes.",
                "tip_it": "Domina le fasce con i 3 attaccanti. Pressa alto e forza gli errori."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Ultra Offensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "All-out attack! Your 3 attackers should score multiple goals. Press relentlessly.",
                "tip_it": "Attacco totale! I tuoi 3 attaccanti devono segnare multipli gol. Pressa senza sosta."
            }
        }
    },
    {
        "id": "41221",
        "name": "4-1-2-2-1",
        "description_en": "Defensive formation with heavily protected center. DMC + 2 DCs create a wall. AML/AMR provide width while lone striker holds the ball.",
        "description_it": "Formazione difensiva con centro fortemente protetto. DMC + 2 DC creano un muro. AML/AMR forniscono ampiezza mentre l'attaccante solitario tiene palla.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MC", "MC", "AML", "AMR", "ST"],
        "strengths_en": ["Heavily protected center", "Strong vs central attacks", "Width on flanks", "Counter-attack potential"],
        "strengths_it": ["Centro fortemente protetto", "Forte contro attacchi centrali", "Ampiezza sulle fasce", "Potenziale di contropiede"],
        "weaknesses_en": ["Lone striker isolated", "Can lack creativity", "Needs pacey wingers"],
        "weaknesses_it": ["Attaccante solitario isolato", "Può mancare creatività", "Richiede ali veloci"],
        "tactic_type_en": "Defensive / Counter",
        "tactic_type_it": "Difensivo / Contropiede",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Ultra Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Park the bus! Use AML/AMR pace on rare counters. Target ST with long balls.",
                "tip_it": "Catenaccio! Usa la velocità di AML/AMR nei rari contropiedi. Punta ST con palle lunghe."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Stay compact. Let AML/AMR push when safe. Strike on transitions.",
                "tip_it": "Resta compatto. Lascia AML/AMR spingere quando è sicuro. Colpisci nelle transizioni."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Push AML/AMR high to support ST. DMC covers while you attack flanks.",
                "tip_it": "Spingi AML/AMR in alto per supportare ST. Il DMC copre mentre attacchi le fasce."
            }
        }
    },
    {
        "id": "3241",
        "name": "3-2-4-1",
        "description_en": "2026 META attacking formation. 2 DMCs provide defensive cover while 4 midfielders overwhelm opposition. Through ball focused with False Nine option.",
        "description_it": "Formazione offensiva META 2026. 2 DMC forniscono copertura difensiva mentre 4 centrocampisti travolgono l'avversario. Focalizzata su passaggi filtranti con opzione Falso Nove.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "DMC", "ML", "MC", "MC", "MR", "ST"],
        "strengths_en": ["Double DMC protection", "Midfield overload", "Through ball potential", "Strong transitions", "False Nine adaptable"],
        "strengths_it": ["Protezione doppio DMC", "Superiorità a centrocampo", "Potenziale passaggi filtranti", "Transizioni forti", "Adattabile a Falso Nove"],
        "weaknesses_en": ["Only 3 defenders", "Lone striker", "Requires stamina", "Can be exposed on flanks"],
        "weaknesses_it": ["Solo 3 difensori", "Attaccante solitario", "Richiede resistenza", "Può essere esposta sulle fasce"],
        "tactic_type_en": "Through Ball / META 2026",
        "tactic_type_it": "Passaggio Filtrante / META 2026",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Both DMCs protect the 3 CBs. Quick counters through the middle to ST.",
                "tip_it": "Entrambi i DMC proteggono i 3 DC. Contropiedi veloci al centro verso ST."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Dominate midfield with 6 players. Through balls to ST for 1v1 with keeper.",
                "tip_it": "Domina il centrocampo con 6 giocatori. Passaggi filtranti per ST in 1v1 col portiere."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Full pressing! 6-man midfield dominates. Through balls will create many chances.",
                "tip_it": "Pressing totale! Il centrocampo a 6 domina. I passaggi filtranti creeranno molte occasioni."
            }
        }
    },
    {
        "id": "5212",
        "name": "5-2-1-2",
        "description_en": "Ultra-defensive formation with 5 at the back. 2 MCs protect while AMC links to the 2 strikers. Best for protecting leads or beating stronger teams.",
        "description_it": "Formazione ultra-difensiva con 5 in difesa. 2 MC proteggono mentre l'AMC collega ai 2 attaccanti. Ideale per proteggere vantaggi o battere squadre più forti.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "MC", "MC", "AMC", "ST", "ST"],
        "strengths_en": ["Maximum defensive cover", "Two striker partnership", "Creative AMC", "Counter-attack ready", "Hard to break down"],
        "strengths_it": ["Massima copertura difensiva", "Partnership di due attaccanti", "AMC creativo", "Pronto al contropiede", "Difficile da sfondare"],
        "weaknesses_en": ["Very defensive", "Lacks midfield numbers", "Wing-backs must be fit"],
        "weaknesses_it": ["Molto difensiva", "Manca numero a centrocampo", "Gli esterni devono essere in forma"],
        "tactic_type_en": "Ultra Defensive / Catenaccio",
        "tactic_type_it": "Ultra Difensivo / Catenaccio",
        "recommended_tactics": {
            "mentality": "Hard Defending",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Ultra Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "FULL CATENACCIO! 5 at back tight. Long balls to 2 strikers on rare counters. 0-0 is victory!",
                "tip_it": "CATENACCIO TOTALE! 5 in difesa stretti. Palle lunghe ai 2 attaccanti nei rari contropiedi. 0-0 è vittoria!"
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Sulle Fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "Stay deep and organized. AMC links to striker duo on transitions.",
                "tip_it": "Resta profondo e organizzato. L'AMC collega alla coppia d'attacco nelle transizioni."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Wing-backs push high. AMC feeds the 2 strikers constantly.",
                "tip_it": "Gli esterni spingono in alto. L'AMC serve costantemente i 2 attaccanti."
            }
        }
    },
    {
        "id": "4321",
        "name": "4-3-2-1 Christmas Tree",
        "description_en": "Classic Italian formation shaped like a Christmas tree. 3 CMs control the middle while 2 AMs create for lone striker. Great for possession play.",
        "description_it": "Classica formazione italiana a forma di albero di Natale. 3 MC controllano il centro mentre 2 trequartisti creano per l'attaccante solitario. Ottima per il possesso palla.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "MC", "AML", "AMR", "ST"],
        "strengths_en": ["Strong central presence", "Two playmakers", "Possession oriented", "Defensively solid", "Counter options"],
        "strengths_it": ["Forte presenza centrale", "Due registi", "Orientata al possesso", "Difensivamente solida", "Opzioni di contropiede"],
        "weaknesses_en": ["Lacks natural wingers", "Can be narrow", "Needs quality AMC players"],
        "weaknesses_it": ["Manca ali naturali", "Può essere stretta", "Richiede giocatori AMC di qualità"],
        "tactic_type_en": "Possession / Italian Style",
        "tactic_type_it": "Possesso / Stile Italiano",
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "Medium",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": True,
                "tip_en": "3 MCs form a wall. Quick transitions through AML/AMR to ST on counters.",
                "tip_it": "3 MC formano un muro. Transizioni veloci tramite AML/AMR verso ST in contropiede."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "A Zona",
                "offside_trap": False,
                "tip_en": "Dominate possession in center. AML/AMR drift in to support ST with creativity.",
                "tip_it": "Domina il possesso al centro. AML/AMR si accentrano per supportare ST con creatività."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Offensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Al Centro",
                "passing_style": "Short",
                "passing_style_it": "Corto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo su Uomo",
                "offside_trap": False,
                "tip_en": "Push AML/AMR high. 5 attackers overwhelm their defense. Score plenty!",
                "tip_it": "Spingi AML/AMR in alto. 5 attaccanti travolgono la loro difesa. Segna tanto!"
            }
        }
    }
]

# ==================== COUNTER TACTICS DATA (EXPANDED) ====================

COUNTER_TACTICS = [
    {
        "formation": "442", 
        "counters": ["41212nd", "4231"],
        "offensive_counter": "4-1-2-1-2 Narrow Diamond",
        "defensive_counter": "4-5-1 V-Style",
        "reason_en": "Diamond midfield overloads 4-4-2's flat four. Attack through the middle to exploit gaps between MC's.",
        "reason_it": "Il diamante a centrocampo sovraccarica il centrocampo piatto del 4-4-2. Attacca al centro per sfruttare gli spazi tra i MC.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Zonal"
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Al Centro",
            "passing_style": "Corto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "A Zona"
        }
    },
    {
        "formation": "433", 
        "counters": ["451v", "4141"],
        "offensive_counter": "4-5-1 V-Style",
        "defensive_counter": "5-4-1",
        "reason_en": "Compact 5-man midfield neutralizes 4-3-3's width. Hit them on the counter when they push forward.",
        "reason_it": "Il centrocampo compatto a 5 neutralizza l'ampiezza del 4-3-3. Colpisci in contropiede quando avanzano.",
        "tactics_en": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "marking": "Zonal"
        },
        "tactics_it": {
            "mentality": "Difensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Lungo",
            "counter_attack": True,
            "pressing": "Basso",
            "marking": "A Zona"
        }
    },
    {
        "formation": "352", 
        "counters": ["433", "343"],
        "offensive_counter": "4-3-3",
        "defensive_counter": "4-2-2-2 Hexagon",
        "reason_en": "Wide formations exploit 3-5-2's exposed flanks. Your wingers will have space against their 3 CBs.",
        "reason_it": "Le formazioni ampie sfruttano i fianchi esposti del 3-5-2. Le tue ali avranno spazio contro i loro 3 DC.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Man-to-Man"
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Misto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "Uomo su Uomo"
        }
    },
    {
        "formation": "4231", 
        "counters": ["541", "3142"],
        "offensive_counter": "3-2-3-2",
        "defensive_counter": "6-4-1",
        "reason_en": "Pack the midfield to nullify their AMC. Counter-attack when they commit players forward.",
        "reason_it": "Riempi il centrocampo per annullare il loro AMC. Contropiede quando portano giocatori in avanti.",
        "tactics_en": {
            "mentality": "Hard Defending",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "marking": "Zonal"
        },
        "tactics_it": {
            "mentality": "Ultra Difensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Lungo",
            "counter_attack": True,
            "pressing": "Basso",
            "marking": "A Zona"
        }
    },
    {
        "formation": "451v", 
        "counters": ["352", "41212nd"],
        "offensive_counter": "3-5-2",
        "defensive_counter": "4-2-2-2 Hexagon",
        "reason_en": "Outnumber their midfield and attack through center. Their lone striker will be isolated.",
        "reason_it": "Supera numericamente il loro centrocampo e attacca al centro. Il loro attaccante solitario sarà isolato.",
        "tactics_en": {
            "mentality": "Normal",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Zonal"
        },
        "tactics_it": {
            "mentality": "Normale",
            "focus_passing": "Al Centro",
            "passing_style": "Corto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "A Zona"
        }
    },
    {
        "formation": "41212nd", 
        "counters": ["433", "31222"],
        "offensive_counter": "3-1-2-2-2",
        "defensive_counter": "4-5-1 V-Style",
        "reason_en": "Attack through flanks - diamond has no natural wingers. Your wide players will dominate.",
        "reason_it": "Attacca sulle fasce - il diamante non ha ali naturali. I tuoi esterni domineranno.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Man-to-Man"
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Misto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "Uomo su Uomo"
        }
    },
    {
        "formation": "343", 
        "counters": ["541", "451v"],
        "offensive_counter": "5-4-1",
        "defensive_counter": "4-5-1",
        "reason_en": "Defensive formations exploit 3-4-3's weak defense. Stay compact and hit them on counter.",
        "reason_it": "Le formazioni difensive sfruttano la difesa debole del 3-4-3. Resta compatto e colpisci in contropiede.",
        "tactics_en": {
            "mentality": "Hard Defending",
            "focus_passing": "Mixed",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "marking": "Zonal"
        },
        "tactics_it": {
            "mentality": "Ultra Difensivo",
            "focus_passing": "Misto",
            "passing_style": "Lungo",
            "counter_attack": True,
            "pressing": "Basso",
            "marking": "A Zona"
        }
    },
    {
        "formation": "541", 
        "counters": ["433", "343"],
        "offensive_counter": "4-3-3",
        "defensive_counter": "4-4-2 Classic",
        "reason_en": "Attacking width stretches their 5-man defense. Patient passing will create openings.",
        "reason_it": "L'ampiezza offensiva distende la loro difesa a 5. Passaggi pazienti creeranno aperture.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Zonal"
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Corto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "A Zona"
        }
    },
    {
        "formation": "4141", 
        "counters": ["4231", "352"],
        "offensive_counter": "4-3-2-1",
        "defensive_counter": "4-5-1 V-Style",
        "reason_en": "Creative formations can bypass the single DMC. Overload their pivot with multiple attackers.",
        "reason_it": "Le formazioni creative possono aggirare il singolo DMC. Sovraccarica il loro pivot con più attaccanti.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "High",
            "marking": "Man-to-Man"
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Lungo",
            "counter_attack": True,
            "pressing": "Alto",
            "marking": "Uomo su Uomo"
        }
    },
    {
        "formation": "4222",
        "counters": ["4312", "433"],
        "offensive_counter": "4-3-1-2",
        "defensive_counter": "4-5-1 V-Style",
        "reason_en": "Target their lack of width. Your ML/MR will have free runs against their narrow shape.",
        "reason_it": "Colpisci la loro mancanza di ampiezza. I tuoi ML/MR avranno corse libere contro la loro forma stretta.",
        "tactics_en": {
            "mentality": "Normal",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "marking": "Zonal"
        },
        "tactics_it": {
            "mentality": "Normale",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Corto",
            "counter_attack": True,
            "pressing": "Alto",
            "marking": "A Zona"
        }
    },
    # ==================== NEW 2025/2026 COUNTER TACTICS ====================
    {
        "formation": "31411",
        "counters": ["433", "4123"],
        "offensive_counter": "4-3-3",
        "defensive_counter": "4-5-1 V-Style",
        "meta_2026": True,
        "reason_en": "Attack the flanks! 3-1-4-1-1 has only 3 CBs and no natural wing coverage. Your AML/AMR or ML/MR will overwhelm their vulnerable wings. Use width and crosses to exploit the 3-man defense.",
        "reason_it": "Attacca le fasce! Il 3-1-4-1-1 ha solo 3 DC e nessuna copertura naturale sulle ali. I tuoi AML/AMR o ML/MR travolgeranno le loro fasce vulnerabili. Usa ampiezza e cross per sfruttare la difesa a 3.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Zonal",
            "tip": "Focus AML/AMR with high crossing and pace. Their DMC can't cover everything."
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Misto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "A Zona",
            "tip": "Concentrati su AML/AMR con alto cross e velocità. Il loro DMC non può coprire tutto."
        }
    },
    {
        "formation": "4123",
        "counters": ["31411", "451v"],
        "offensive_counter": "3-1-4-1-1",
        "defensive_counter": "4-5-1 V-Style",
        "meta_2026": True,
        "reason_en": "Dominate midfield to nullify their 3 forwards. 3-1-4-1-1's 7-man midfield overwhelms 4-1-2-3's 2 MCs. DMC backward arrow essential to block their AMC/ST link.",
        "reason_it": "Domina il centrocampo per annullare i loro 3 attaccanti. Il centrocampo a 7 del 3-1-4-1-1 travolge i 2 MC del 4-1-2-3. Freccia in basso sul DMC essenziale per bloccare il collegamento AMC/ST.",
        "tactics_en": {
            "mentality": "Normal",
            "focus_passing": "Mixed",
            "passing_style": "Mixed",
            "counter_attack": True,
            "pressing": "Low",
            "marking": "Zonal",
            "tip": "Your 7 midfielders vs their 3. Control the game and counter through AMC."
        },
        "tactics_it": {
            "mentality": "Normale",
            "focus_passing": "Misto",
            "passing_style": "Misto",
            "counter_attack": True,
            "pressing": "Basso",
            "marking": "A Zona",
            "tip": "I tuoi 7 centrocampisti contro i loro 3. Controlla la partita e contropiede tramite AMC."
        }
    },
    {
        "formation": "41221",
        "counters": ["433", "343"],
        "offensive_counter": "4-3-3",
        "defensive_counter": "3-4-3",
        "meta_2026": True,
        "reason_en": "Attack the wings aggressively. 4-1-2-2-1's strength is the protected center, so avoid it. Your wingers should target their exposed DL/DR with pace and crossing.",
        "reason_it": "Attacca le fasce aggressivamente. La forza del 4-1-2-2-1 è il centro protetto, quindi evitalo. Le tue ali devono puntare i loro DL/DR esposti con velocità e cross.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Man-to-Man",
            "tip": "Avoid the center! Their DMC + 2 DCs are a wall. Attack ONLY on flanks."
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Misto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "Uomo su Uomo",
            "tip": "Evita il centro! Il loro DMC + 2 DC sono un muro. Attacca SOLO sulle fasce."
        }
    },
    {
        "formation": "3241",
        "counters": ["433", "4123"],
        "offensive_counter": "4-3-3",
        "defensive_counter": "4-1-2-3",
        "meta_2026": True,
        "reason_en": "Target the 3 CBs with wide attackers. 3-2-4-1's double DMC protects center well, so attack flanks. Your AML/AMR will have space against their narrow shape.",
        "reason_it": "Punta i 3 DC con attaccanti larghi. Il doppio DMC del 3-2-4-1 protegge bene il centro, quindi attacca le fasce. I tuoi AML/AMR avranno spazio contro la loro forma stretta.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Zonal",
            "tip": "Width is key! Their 2 DMCs cover center. Use fast wingers to exploit the 3 CBs."
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Misto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "A Zona",
            "tip": "L'ampiezza è la chiave! I loro 2 DMC coprono il centro. Usa ali veloci per sfruttare i 3 DC."
        }
    },
    {
        "formation": "5212",
        "counters": ["433", "31411"],
        "offensive_counter": "4-3-3",
        "defensive_counter": "3-1-4-1-1",
        "meta_2026": True,
        "reason_en": "Patient possession to break down their 5-man defense. They have only 2 MCs, so dominate midfield with numerical advantage. Use through balls to exploit gaps behind wing-backs.",
        "reason_it": "Possesso paziente per sfondare la loro difesa a 5. Hanno solo 2 MC, quindi domina il centrocampo con vantaggio numerico. Usa passaggi filtranti per sfruttare gli spazi dietro gli esterni.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Mixed",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Man-to-Man",
            "tip": "They will sit deep. Be patient with short passing. Target spaces when wing-backs push up."
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Misto",
            "passing_style": "Corto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "Uomo su Uomo",
            "tip": "Si chiuderanno. Sii paziente con passaggi corti. Punta gli spazi quando gli esterni salgono."
        }
    },
    {
        "formation": "4321",
        "counters": ["433", "31411"],
        "offensive_counter": "4-3-3",
        "defensive_counter": "3-1-4-1-1",
        "meta_2026": True,
        "reason_en": "Attack the flanks to exploit their narrow shape. Christmas Tree has no natural wingers - your ML/MR will dominate. Use width and pace to stretch their 3 MCs.",
        "reason_it": "Attacca le fasce per sfruttare la loro forma stretta. L'Albero di Natale non ha ali naturali - i tuoi ML/MR domineranno. Usa ampiezza e velocità per allargare i loro 3 MC.",
        "tactics_en": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "marking": "Zonal",
            "tip": "They're narrow! Attack wide with pacey ML/MR. Their AML/AMR must track back, tiring them."
        },
        "tactics_it": {
            "mentality": "Offensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Misto",
            "counter_attack": False,
            "pressing": "Alto",
            "marking": "A Zona",
            "tip": "Sono stretti! Attacca largo con ML/MR veloci. I loro AML/AMR devono rientrare, stancandosi."
        }
    },
    {
        "formation": "31231",
        "counters": ["451v", "5212"],
        "offensive_counter": "4-5-1 V-Style",
        "defensive_counter": "5-2-1-2",
        "meta_2026": True,
        "reason_en": "Counter their 3-at-back with quick transitions. Pack the midfield to match their numbers, then hit on counters. Target the exposed flanks when their wing-players push forward.",
        "reason_it": "Controbatti la loro difesa a 3 con transizioni veloci. Riempi il centrocampo per pareggiare i numeri, poi colpisci in contropiede. Punta le fasce esposte quando i loro esterni avanzano.",
        "tactics_en": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "marking": "Zonal",
            "tip": "Let them come to you. Their 3 CBs are vulnerable to fast counters on flanks."
        },
        "tactics_it": {
            "mentality": "Difensivo",
            "focus_passing": "Sulle Fasce",
            "passing_style": "Lungo",
            "counter_attack": True,
            "pressing": "Basso",
            "marking": "A Zona",
            "tip": "Lasciali venire. I loro 3 DC sono vulnerabili a contropiedi veloci sulle fasce."
        }
    }
]

# ==================== SCOUT TIPS DATA (EXPANDED) ====================

SCOUT_TIPS = [
    {
        "id": "1",
        "category": "defense",
        "title_en": "Center Back Selection",
        "title_it": "Selezione Difensori Centrali",
        "content_en": "Look for CBs with high Tackling, Heading, and Positioning. Speed is important to recover against fast strikers. Prioritize players with 4+ stars. Use 2 DC vs 1 ST, 3 DC vs 2 ST, and DL-DC-DR vs ST-AML-AMR.",
        "content_it": "Cerca DC con alto Contrasto, Colpo di Testa e Posizionamento. La velocità è importante per recuperare contro attaccanti veloci. Dai priorità a giocatori con 4+ stelle. Usa 2 DC vs 1 ST, 3 DC vs 2 ST, e DL-DC-DR vs ST-AML-AMR."
    },
    {
        "id": "2",
        "category": "midfield",
        "title_en": "Midfield Balance",
        "title_it": "Equilibrio a Centrocampo",
        "content_en": "Have a mix of defensive (DMC) and attacking (AMC) midfielders. ML/MR should have good Crossing and Pace. Central midfielders need Passing and Stamina. Box-to-box midfielders are gold!",
        "content_it": "Avere un mix di centrocampisti difensivi (DMC) e offensivi (AMC). ML/MR devono avere buon Cross e Velocità. I centrocampisti centrali necessitano Passaggio e Resistenza. I centrocampisti box-to-box sono oro!"
    },
    {
        "id": "3",
        "category": "attack",
        "title_en": "Striker Types",
        "title_it": "Tipi di Attaccante",
        "content_en": "Target men need Heading and Strength. Speedsters need Pace and Finishing. Complete forwards are rare but valuable. Use 2 ST to break 4 defenders, 3 ST (or ST-AML-AMR) to break 3 defenders.",
        "content_it": "I pivot necessitano Colpo di Testa e Forza. I velocisti necessitano Velocità e Finalizzazione. Gli attaccanti completi sono rari ma preziosi. Usa 2 ST vs 4 difensori, 3 ST (o ST-AML-AMR) vs 3 difensori."
    },
    {
        "id": "4",
        "category": "training",
        "title_en": "Training Priority",
        "title_it": "Priorità Allenamento",
        "content_en": "Focus training on your starting 11 first. Use Quick Training early in seasons. Save intensive drills for important matches. Maintain 80/80 teamplay before big games. Train GK: One-on-One, Aerial, Reflexes. Train DC: Tackling, Heading, Positioning.",
        "content_it": "Concentra l'allenamento prima sui titolari. Usa Allenamento Rapido all'inizio delle stagioni. Conserva gli esercizi intensivi per partite importanti. Mantieni 80/80 di affiatamento prima di grandi partite. Allena GK: Uno contro Uno, Aereo, Riflessi. Allena DC: Contrasto, Colpo di Testa, Posizionamento."
    },
    {
        "id": "5",
        "category": "budget",
        "title_en": "Token Management",
        "title_it": "Gestione Token",
        "content_en": "Don't spend more than 30 tokens for a single auction player. Spend at least 15 tokens for youth academy per season. Never buy assistant players for more than 50 tokens. Sign TV rights for daily token bonus.",
        "content_it": "Non spendere più di 30 token per un singolo giocatore all'asta. Spendi almeno 15 token per l'accademia giovanile per stagione. Mai comprare assistenti per più di 50 token. Firma i diritti TV per bonus token giornaliero."
    },
    {
        "id": "6",
        "category": "tactics",
        "title_en": "Team Mentality Explained",
        "title_it": "Mentalità di Squadra Spiegata",
        "content_en": "Hard Defending: Deep position, counter-attacks. Defending: Slightly higher, counter from midfield. Normal: Balanced approach. Attacking: Higher line, fullbacks support. Hard Attacking: All-out attack from opponent's half.",
        "content_it": "Ultra Difensivo: Posizione arretrata, contropiedi. Difensivo: Leggermente più alto, contropiede dal centrocampo. Normale: Approccio bilanciato. Offensivo: Linea più alta, terzini in attacco. Ultra Offensivo: Attacco totale dalla metà campo avversaria."
    },
    {
        "id": "7",
        "category": "tactics",
        "title_en": "Focus Passing Guide",
        "title_it": "Guida Focus Passaggio",
        "content_en": "Mixed: Play everywhere on pitch. Down Both Flanks: Use wide players to create. Right/Left Flank: Focus one side. Through the Middle: Central penetration. Match your passing to your formation!",
        "content_it": "Misto: Gioca ovunque sul campo. Sulle Fasce: Usa esterni per creare. Fascia Destra/Sinistra: Concentra su un lato. Al Centro: Penetrazione centrale. Adatta i passaggi alla tua formazione!"
    },
    {
        "id": "8",
        "category": "tactics",
        "title_en": "Counter-Attack & Pressing",
        "title_it": "Contropiede & Pressing",
        "content_en": "Turn ON counter-attacks if opponent has more possession. Turn OFF if you dominate. High press wins ball high but tires players. Low press saves stamina for 2 daily games. Use high press against weaker teams!",
        "content_it": "Attiva contropiede se l'avversario ha più possesso. Disattiva se domini. Pressing alto recupera palla in alto ma stanca. Pressing basso risparmia resistenza per 2 partite giornaliere. Usa pressing alto contro squadre più deboli!"
    },
    {
        "id": "9",
        "category": "tactics",
        "title_en": "Marking & Tackling",
        "title_it": "Marcatura & Contrasti",
        "content_en": "Zonal marking: Players stay in formation positions. Man-to-man: Mark specific attackers (tires defenders faster). Easy tackle: Few fouls, less risky. Hard tackle: More fouls but wins more balls. Match opponent's playstyle!",
        "content_it": "Marcatura a zona: Giocatori restano nelle posizioni. Uomo su uomo: Marca attaccanti specifici (stanca i difensori). Contrasto facile: Pochi falli, meno rischioso. Contrasto duro: Più falli ma recupera più palle. Adatta allo stile dell'avversario!"
    },
    {
        "id": "10",
        "category": "tactics",
        "title_en": "Offside Trap",
        "title_it": "Fuorigioco",
        "content_en": "Turn ON offside trap if opponent plays long balls to strikers. Turn OFF if opponent plays short passes. Risky against fast strikers! Best used with high defensive line and coordinated back line.",
        "content_it": "Attiva fuorigioco se l'avversario gioca palle lunghe agli attaccanti. Disattiva se gioca passaggi corti. Rischioso contro attaccanti veloci! Meglio con linea difensiva alta e difesa coordinata."
    },
    {
        "id": "11",
        "category": "defense",
        "title_en": "Full-Back Selection",
        "title_it": "Selezione Terzini",
        "content_en": "DR/DL need pace and stamina for overlapping runs. Look for good crossing and tackling. Wing-backs (DML/DMR) need even more stamina. In 3-back systems, they are your only width!",
        "content_it": "DR/DL necessitano velocità e resistenza per sovrapposizioni. Cerca buon cross e contrasto. I esterni (DML/DMR) necessitano ancora più resistenza. Nei sistemi a 3, sono la tua unica ampiezza!"
    },
    {
        "id": "12",
        "category": "attack",
        "title_en": "Winger Selection",
        "title_it": "Selezione Ali",
        "content_en": "ML/MR need Pace, Crossing, and Dribbling. AML/AMR should have Finishing too. Inverted wingers (right-footed on left) can cut inside and shoot. Classic wingers provide crosses for headers.",
        "content_it": "ML/MR necessitano Velocità, Cross e Dribbling. AML/AMR dovrebbero avere anche Finalizzazione. Ali invertite (destro a sinistra) possono rientrare e tirare. Ali classiche forniscono cross per colpi di testa."
    },
    {
        "id": "13",
        "category": "training",
        "title_en": "Position Training Drills",
        "title_it": "Esercizi per Posizione",
        "content_en": "GK: One-on-One, Aerial, Reflexes. DC: Tackling, Heading, Positioning. DR/DL: Tackling, Pace, Crossing. MC: Passing, Tackling, Stamina. AMC: Passing, Finishing, Creativity. ST: Finishing, Heading, Pace.",
        "content_it": "GK: Uno contro Uno, Aereo, Riflessi. DC: Contrasto, Colpo di Testa, Posizionamento. DR/DL: Contrasto, Velocità, Cross. MC: Passaggio, Contrasto, Resistenza. AMC: Passaggio, Finalizzazione, Creatività. ST: Finalizzazione, Colpo di Testa, Velocità."
    },
    {
        "id": "14",
        "category": "budget",
        "title_en": "Youth Academy Tips",
        "title_it": "Consigli Accademia Giovanile",
        "content_en": "Try to get at least three 6-star players from youth academy every season. These young players will help your team win trophies in future seasons. Youth players develop faster with regular playing time.",
        "content_it": "Cerca di ottenere almeno tre giocatori da 6 stelle dall'accademia ogni stagione. Questi giovani giocatori aiuteranno la squadra a vincere trofei nelle stagioni future. I giovani si sviluppano più velocemente con minuti regolari."
    },
    {
        "id": "15",
        "category": "general",
        "title_en": "Beat Stronger Opponents",
        "title_it": "Battere Avversari più Forti",
        "content_en": "Play counter-attacking football. Be strong in numbers in defense. Mark all opponent's attackers. Play long balls for counter-attacks - don't try to out-pass stronger midfielders. Let them attack, then strike!",
        "content_it": "Gioca calcio di contropiede. Sii forte numericamente in difesa. Marca tutti gli attaccanti avversari. Gioca palle lunghe per contropiedi - non provare a superare centrocampisti più forti. Lasciali attaccare, poi colpisci!"
    },
    {
        "id": "16",
        "category": "general",
        "title_en": "Pre-Match Preparation",
        "title_it": "Preparazione Pre-Partita",
        "content_en": "Always provide full Morale Boost and Fitness Condition before important matches. Add friends in Top Eleven - they help you get more possession during matches! Review opponent's formation and adjust tactics.",
        "content_it": "Fornisci sempre Morale e Condizione al massimo prima di partite importanti. Aggiungi amici in Top Eleven - ti aiutano ad avere più possesso! Rivedi la formazione avversaria e adatta le tattiche."
    }
]

# ==================== FORMATIONS ENDPOINTS ====================

@api_router.get("/formations")
async def get_formations():
    """Get all formations"""
    return FORMATIONS

@api_router.get("/formations/{formation_id}")
async def get_formation(formation_id: str):
    """Get a specific formation"""
    for formation in FORMATIONS:
        if formation["id"] == formation_id:
            return formation
    raise HTTPException(status_code=404, detail="Formation not found")

# ==================== COUNTER TACTICS ENDPOINTS ====================

@api_router.get("/counters")
async def get_counter_tactics():
    """Get all counter tactics"""
    return COUNTER_TACTICS

@api_router.get("/counters/{formation_id}")
async def get_counter_for_formation(formation_id: str):
    """Get counter tactics for a specific formation"""
    for counter in COUNTER_TACTICS:
        if counter["formation"] == formation_id:
            return counter
    raise HTTPException(status_code=404, detail="Counter tactics not found")

# ==================== SCOUT TIPS ENDPOINTS ====================

@api_router.get("/scout-tips")
async def get_scout_tips():
    """Get all scout tips"""
    return SCOUT_TIPS

@api_router.get("/scout-tips/{category}")
async def get_scout_tips_by_category(category: str):
    """Get scout tips by category"""
    tips = [tip for tip in SCOUT_TIPS if tip["category"] == category]
    if not tips:
        raise HTTPException(status_code=404, detail="No tips found for this category")
    return tips

# ==================== FAVORITES ENDPOINTS ====================

@api_router.post("/favorites")
async def add_favorite(request: Request, formation_id: str):
    """Add a formation to favorites"""
    user = await get_current_user(request)
    
    # Check if already favorite
    existing = await db.favorites.find_one(
        {"user_id": user.user_id, "formation_id": formation_id},
        {"_id": 0}
    )
    
    if existing:
        raise HTTPException(status_code=400, detail="Already in favorites")
    
    favorite = {
        "id": str(uuid.uuid4()),
        "user_id": user.user_id,
        "formation_id": formation_id,
        "created_at": datetime.now(timezone.utc)
    }
    
    await db.favorites.insert_one(favorite)
    return {"message": "Added to favorites"}

@api_router.delete("/favorites/{formation_id}")
async def remove_favorite(request: Request, formation_id: str):
    """Remove a formation from favorites"""
    user = await get_current_user(request)
    result = await db.favorites.delete_one(
        {"user_id": user.user_id, "formation_id": formation_id}
    )
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Favorite not found")
    
    return {"message": "Removed from favorites"}

@api_router.get("/favorites")
async def get_favorites(request: Request):
    """Get user's favorite formations"""
    user = await get_current_user(request)
    favorites = await db.favorites.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).to_list(100)
    
    return favorites

# ==================== AI CHAT ENDPOINTS ====================

@api_router.post("/ai/chat")
async def ai_chat(request: Request, chat_request: ChatRequest):
    """AI-powered tactics assistant"""
    user = await get_current_user(request)
    
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="AI service not configured")
    
    # Get language-specific system message
    if chat_request.language == 'it':
        system_message = """Sei un esperto assistente tattico per Top Eleven, il gioco di calcio manageriale. 
        Aiuti i giocatori con:
        - Suggerimenti su formazioni e tattiche
        - Contro-tattiche per battere avversari
        - Consigli su acquisti e scout giocatori
        - Strategie di allenamento e gestione rosa
        - Tips per vincere campionati e coppe
        
        Rispondi sempre in italiano in modo chiaro e conciso. Usa emoji per rendere le risposte più coinvolgenti."""
    else:
        system_message = """You are an expert tactical assistant for Top Eleven, the football manager game.
        You help players with:
        - Formation and tactics suggestions
        - Counter-tactics to beat opponents
        - Player scouting and transfer advice
        - Training strategies and squad management
        - Tips for winning leagues and cups
        
        Always respond in English, clearly and concisely. Use emojis to make responses engaging."""
    
    try:
        # Initialize chat
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"top11_{user.user_id}_{datetime.now().timestamp()}",
            system_message=system_message
        )
        chat.with_model("openai", "gpt-4o")
        
        # Send message
        user_message = UserMessage(text=chat_request.message)
        response = await chat.send_message(user_message)
        
        # Save to chat history
        user_msg = {
            "id": str(uuid.uuid4()),
            "user_id": user.user_id,
            "role": "user",
            "content": chat_request.message,
            "created_at": datetime.now(timezone.utc)
        }
        assistant_msg = {
            "id": str(uuid.uuid4()),
            "user_id": user.user_id,
            "role": "assistant",
            "content": response,
            "created_at": datetime.now(timezone.utc)
        }
        
        await db.chat_history.insert_many([user_msg, assistant_msg])
        
        return {"response": response}
        
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        raise HTTPException(status_code=500, detail="AI service error")

@api_router.get("/ai/history")
async def get_chat_history(request: Request, limit: int = 50):
    """Get user's chat history"""
    user = await get_current_user(request)
    
    history = await db.chat_history.find(
        {"user_id": user.user_id},
        {"_id": 0}
    ).sort("created_at", -1).limit(limit).to_list(limit)
    
    return list(reversed(history))

@api_router.delete("/ai/history")
async def clear_chat_history(request: Request):
    """Clear user's chat history"""
    user = await get_current_user(request)
    await db.chat_history.delete_many({"user_id": user.user_id})
    return {"message": "Chat history cleared"}

# ==================== HEALTH CHECK ====================

@api_router.get("/")
async def root():
    return {"message": "Top Eleven Tactics API", "version": "1.0.0"}

@api_router.get("/health")
async def health():
    return {"status": "healthy"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
