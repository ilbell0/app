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
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
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
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Hard",
            "marking": "Man-to-Man",
            "offside_trap": False
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
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
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
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
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
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
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
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
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
        "recommended_tactics": {
            "mentality": "Hard Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Hard",
            "marking": "Man-to-Man",
            "offside_trap": False
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
        "recommended_tactics": {
            "mentality": "Hard Defending",
            "focus_passing": "Mixed",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": True
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
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Mixed",
            "passing_style": "Short",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
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
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
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
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Mixed",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Man-to-Man",
            "offside_trap": True
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
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
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
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
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
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Mixed",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
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
