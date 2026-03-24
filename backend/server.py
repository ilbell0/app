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

# ==================== FORMATIONS DATA (EXPANDED from PDF Database v2) ====================

# LEGEND (from PDF):
# N = Narrow (Stretto), W = Wide (Largo), F = Flat (Piatto)
# V = V-Style (DMC-MC-MC-AML-AMR), B = Butterfly (3N-2W-2N-2W-1)
# C = Curved (3DC + DL/DR avanzati), D = Dandelion (3N-1-3W-1-2)
# H = Hexagon (MC-MC-AML-AMR-ST-ST), ET = Eiffel Tower (3-2N-3-1-1)
# ML = Maple Leaf (3W-2N-3W-1-1), ND = Narrow Diamond (DMC-MC-MC-AMC-ST-ST)
# WD = Wide Diamond (DMC-AML-AMR-AMC-ST-ST), XT = Xmas Tree (4-3W-2N-1)
# X = X-Style (5-2-1-2 con DML/DMR)

FORMATIONS = [
    {
        "id": "442c",
        "name": "4-4-2 C (Classic)",
        "description_en": "Classic balanced formation. Strong in both defense and attack with 4 defenders, 4 midfielders, and 2 strikers. One of the oldest and most reliable formations in football.",
        "description_it": "Formazione bilanciata classica. Forte in ampiezza. 4 difensori, 4 centrocampisti e 2 attaccanti.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
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
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Stay compact and let them come. Use long balls to your strikers on counter.",
                "tip_it": "Resta compatto e lasciali venire. Usa palle lunghe agli attaccanti in contropiede."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Play your natural game. Use width and crosses to find your two strikers.",
                "tip_it": "Gioca il tuo gioco naturale. Usa l'ampiezza e i cross per trovare i due attaccanti."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Dominate with high pressing and quick passing. Overwhelm their defense with numbers.",
                "tip_it": "Domina con pressing alto e passaggi veloci. Travolgi la loro difesa con i numeri."
            }
        }
    },
    {
        "id": "41212nd",
        "name": "4-1-2-1-2 ND (Narrow Diamond)",
        "description_en": "Narrow diamond midfield formation. Strong through the center with DMC protecting defense and AMC linking play. Flanks are vulnerable - attack down the wings against this.",
        "description_it": "Diamond stretto. DMC protegge la difesa e AMC collega il gioco. I fianchi sono vulnerabili: attacca sulle ali contro questa formazione.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MC", "MC", "AMC", "ST", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
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
            "pressing": "Normal",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "DMC shields the back 4. Long balls to striker partnership on counters.",
                "tip_it": "Il DMC protegge la difesa a 4. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "Normal",
                "pressing_it": "Normale",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Control the center and let AMC create for the 2 strikers. Be patient.",
                "tip_it": "Controlla il centro e lascia che l'AMC crei per i 2 attaccanti. Sii paziente."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Dominate the center completely. Your AMC should feast on their weak midfield.",
                "tip_it": "Domina il centro completamente. Il tuo AMC deve banchettare sul loro centrocampo debole."
            }
        }
    },
    {
        "id": "41212wd",
        "name": "4-1-2-1-2 WD (Wide Diamond)",
        "description_en": "Wide diamond with high AML/AMR. More width than narrow diamond but vulnerable in the center.",
        "description_it": "Diamond largo. AML/AMR alti. Vulnerabile nel centro.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "AML", "AMR", "AMC", "ST", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
        "strengths_en": ["Width in attack", "Creative AMC", "Two strikers", "Flexible wingers"],
        "strengths_it": ["Ampiezza in attacco", "AMC creativo", "Due attaccanti", "Ali flessibili"],
        "weaknesses_en": ["Vulnerable center", "No central midfield", "Exposed to central attacks"],
        "weaknesses_it": ["Centro vulnerabile", "Nessun centrocampo centrale", "Esposta ad attacchi centrali"],
        "tactic_type_en": "Attacking / Wide",
        "tactic_type_it": "Attaccante / Largo",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Stay compact. Use AML/AMR pace on counters to find strikers.",
                "tip_it": "Resta compatto. Usa la velocità di AML/AMR in contropiede per trovare gli attaccanti."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Use width with AML/AMR. AMC links play between midfield and strikers.",
                "tip_it": "Usa l'ampiezza con AML/AMR. L'AMC collega centrocampo e attaccanti."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Push AML/AMR high. Overload their flanks with width and crosses.",
                "tip_it": "Spingi AML/AMR in alto. Sovraccarica le loro fasce con ampiezza e cross."
            }
        }
    },
    {
        "id": "451v",
        "name": "4-5-1 V (V-Style)",
        "description_en": "Defensive V-shaped formation with AML-AMR high. DMC anchors the midfield. Best for counter-attacking. ★ Arrow forward on AML and AMR.",
        "description_it": "Formazione difensiva a V con AML-AMR alti. DMC ancora il centrocampo. Ideale per contropiede. ★ Frecce avanti a AML e AMR.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MC", "MC", "AML", "AMR", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
        "strengths_en": ["Defensive solidity", "Midfield dominance", "Counter-attack potential", "Flexible wings"],
        "strengths_it": ["Solidità difensiva", "Dominio a centrocampo", "Potenziale di contropiede", "Ali flessibili"],
        "weaknesses_en": ["Lone striker", "Limited attacking options", "Needs fast wingers"],
        "weaknesses_it": ["Attaccante solitario", "Opzioni offensive limitate", "Richiede ali veloci"],
        "tactic_type_en": "Counter-Attack / Defensive",
        "tactic_type_it": "Contropiede / Difensivo",
        "arrows": "★ AML↑ AMR↑",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Park the bus! Stay deep and hit them hard on counters with fast AML/AMR.",
                "tip_it": "Catenaccio! Resta arretrato e colpisci forte in contropiede con AML/AMR veloci."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Control game through midfield. Use arrows on AML/AMR for width.",
                "tip_it": "Controlla il gioco dal centrocampo. Usa frecce su AML/AMR per l'ampiezza."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push up and dominate midfield. Your 5-man midfield should overwhelm theirs.",
                "tip_it": "Spingi e domina il centrocampo. I tuoi 5 centrocampisti devono sopraffare i loro."
            }
        }
    },
    {
        "id": "451f",
        "name": "4-5-1 F (Flat)",
        "description_en": "5 flat midfielders. Great for counter-attacking and controlling possession. Defensive but lethal on breaks.",
        "description_it": "5 centrocampisti piatti. Buono in contropiede e controllo possesso. Difensivo ma letale nelle ripartenze.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MR", "MC", "MC", "MC", "ML", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
        "strengths_en": ["5-man midfield", "Counter-attack", "Defensive solidity", "Width control"],
        "strengths_it": ["Centrocampo a 5", "Contropiede", "Solidità difensiva", "Controllo ampiezza"],
        "weaknesses_en": ["Lone striker isolated", "Limited attack", "Predictable"],
        "weaknesses_it": ["Attaccante isolato", "Attacco limitato", "Prevedibile"],
        "tactic_type_en": "Counter-Attack / Defensive",
        "tactic_type_it": "Contropiede / Difensivo",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Mixed",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "5 flat midfielders block everything. Counter with long balls to lone ST.",
                "tip_it": "5 centrocampisti piatti bloccano tutto. Contropiede con palle lunghe al ST solitario."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Control midfield with 5 players. Wait for counter opportunities.",
                "tip_it": "Controlla il centrocampo con 5 giocatori. Aspetta occasioni di contropiede."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push wide midfielders up. Use width to create for the lone striker.",
                "tip_it": "Spingi gli esterni in alto. Usa l'ampiezza per creare per l'attaccante solitario."
            }
        }
    },
    {
        "id": "4231",
        "name": "4-2-3-1",
        "description_en": "Modern tactical formation with 2 MCs and 3 attacking mids behind lone striker. ★ Defensive arrows on 3DC, ML and MR.",
        "description_it": "Formazione tattica moderna con 2 MC e 3 trequartisti dietro attaccante solitario. ★ Frecce difensive a 3DC, ML e MR.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "AML", "AMC", "AMR", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
        "strengths_en": ["Defensive stability", "Creative playmaker", "Compact midfield", "Flexible"],
        "strengths_it": ["Stabilità difensiva", "Regista creativo", "Centrocampo compatto", "Flessibile"],
        "weaknesses_en": ["Lone striker isolated", "Depends heavily on AMC", "Can lack width"],
        "weaknesses_it": ["Attaccante solitario isolato", "Dipende molto dall'AMC", "Può mancare ampiezza"],
        "tactic_type_en": "Balanced / Counter-Attack",
        "tactic_type_it": "Bilanciato / Contropiede",
        "arrows": "★ DC↓ DL↓ DR↓ ML↓ MR↓",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "2 MCs protect defense. Use AMC to link play on counter-attacks.",
                "tip_it": "2 MC proteggono la difesa. Usa l'AMC per collegare in contropiede."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Let AMC orchestrate attacks. Use AML/AMR width to create for the lone striker.",
                "tip_it": "Lascia l'AMC orchestrare gli attacchi. Usa AML/AMR per creare per l'attaccante."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Push your AML/AMR high. Overload their defense with creative play through AMC.",
                "tip_it": "Spingi AML/AMR in avanti. Sovraccarica la difesa con gioco creativo dall'AMC."
            }
        }
    },
    {
        "id": "4222h",
        "name": "4-2-2-2 H (Hexagon)",
        "description_en": "Compact Hexagon formation with 2 MCs, 2 AMs, and 2 strikers. ★ Arrows forward on DL, DR, AML, AMR.",
        "description_it": "Formazione compatta Hexagon con 2 MC, 2 trequartisti e 2 attaccanti. ★ Frecce avanti a DL, DR, AML, AMR.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "AML", "AMR", "ST", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
        "strengths_en": ["Central control", "Two partnerships", "Compact shape", "Transitions well"],
        "strengths_it": ["Controllo centrale", "Due partnership", "Forma compatta", "Buone transizioni"],
        "weaknesses_en": ["Lacks width", "No natural wingers", "Predictable"],
        "weaknesses_it": ["Manca ampiezza", "Nessuna ala naturale", "Prevedibile"],
        "tactic_type_en": "Central / Transition",
        "tactic_type_it": "Centrale / Transizione",
        "arrows": "★ DL↑ DR↑ AML↑ AMR↑",
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
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Stay compact in center. Use the 2 striker partnership to hold the ball on counters.",
                "tip_it": "Resta compatto al centro. Usa la coppia d'attacco per tenere palla nei contropiedi."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Control center with compact shape. AML/AMR drift in to support strikers.",
                "tip_it": "Controlla il centro con la forma compatta. AML/AMR accentrarsi per supportare gli attaccanti."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Overwhelm center! Your 4 central attackers should dominate their midfield.",
                "tip_it": "Travolgi il centro! I tuoi 4 attaccanti centrali devono dominare il loro centrocampo."
            }
        }
    },
    {
        "id": "352f",
        "name": "3-5-2 F (Flat)",
        "description_en": "Midfield-dominant with 5 flat midfielders. No full-backs - exploit opponent's free wings against this formation.",
        "description_it": "Dominante a centrocampo con 5 centrocampisti piatti. Nessun terzino - sfrutta le ali libere del rivale.",
        "positions": ["GK", "DC", "DC", "DC", "MR", "MC", "MC", "MC", "ML", "ST", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["Midfield control", "Numerical advantage in center", "Partnership up front"],
        "strengths_it": ["Controllo del centrocampo", "Vantaggio numerico al centro", "Partnership in attacco"],
        "weaknesses_en": ["Exposed flanks", "No full-backs", "Weak against wide formations"],
        "weaknesses_it": ["Fianchi esposti", "Nessun terzino", "Debole contro formazioni ampie"],
        "tactic_type_en": "Attacking / High Press",
        "tactic_type_it": "Attaccante / Pressing Alto",
        "recommended_tactics": {
            "mentality": "Attacking",
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
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": True,
                "tip_en": "Keep 5 midfielders tight. Counter through striker partnership.",
                "tip_it": "Tieni i 5 centrocampisti stretti. Contropiede attraverso la coppia d'attacco."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": True,
                "tip_en": "Dominate midfield with 5 players. ML/MR overlap for width.",
                "tip_it": "Domina il centrocampo con 5 giocatori. ML/MR sovrappongono per ampiezza."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "All-out attack with 7 players forward. Overwhelm their defense!",
                "tip_it": "Attacco totale con 7 giocatori in avanti. Travolgi la loro difesa!"
            }
        }
    },
    {
        "id": "352v",
        "name": "3-5-2 V (V-Style)",
        "description_en": "V-style 3-5-2 with high AML/AMR. Effective against crowded midfield but open wings.",
        "description_it": "3-5-2 V-style con AML/AMR alti. Efficace contro centrocampo affollato ma ali scoperte.",
        "positions": ["GK", "DC", "DC", "DC", "MC", "MC", "MC", "AML", "AMR", "ST", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["High wingers", "Midfield control", "Two strikers", "Pressing"],
        "strengths_it": ["Ali alte", "Controllo centrocampo", "Due attaccanti", "Pressing"],
        "weaknesses_en": ["Exposed 3 CBs", "No full-backs", "Vulnerable on flanks"],
        "weaknesses_it": ["3 DC esposti", "Nessun terzino", "Vulnerabile sulle fasce"],
        "tactic_type_en": "Attacking / Wide High",
        "tactic_type_it": "Attaccante / Ali Alte",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": True,
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
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "High AML/AMR exploit space on counters. Protect 3 CBs.",
                "tip_it": "AML/AMR alti sfruttano spazi in contropiede. Proteggi i 3 DC."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Use width with AML/AMR. Strike partnership creates chances.",
                "tip_it": "Usa l'ampiezza con AML/AMR. La coppia d'attacco crea occasioni."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Push AML/AMR very high. Overwhelm with 5 attackers!",
                "tip_it": "Spingi AML/AMR molto in alto. Travolgi con 5 attaccanti!"
            }
        }
    },
    {
        "id": "3142",
        "name": "3-1-4-2",
        "description_en": "DMC anchors the midfield with 4 wide midfielders. Strong against 4-3-3 and formations with 3 attackers.",
        "description_it": "DMC ancora il centrocampo con 4 centrocampisti larghi. Forte contro 4-3-3 e formazioni con 3 attaccanti.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "MR", "MC", "MC", "ML", "ST", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["DMC protection", "Wide midfield", "Two strikers", "Counter 4-3-3"],
        "strengths_it": ["Protezione DMC", "Centrocampo ampio", "Due attaccanti", "Contrasta 4-3-3"],
        "weaknesses_en": ["3 CBs exposed", "Needs fit ML/MR", "Vulnerable to counters"],
        "weaknesses_it": ["3 DC esposti", "Richiede ML/MR in forma", "Vulnerabile ai contropiedi"],
        "tactic_type_en": "Counter-Attack / Anti-433",
        "tactic_type_it": "Contropiede / Anti-433",
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
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": True,
                "tip_en": "DMC shields 3 CBs. Long balls to striker partnership on counters.",
                "tip_it": "Il DMC protegge i 3 DC. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": True,
                "tip_en": "Press high with 4 midfielders. DMC covers. Strike on transitions.",
                "tip_it": "Pressa alto con 4 centrocampisti. Il DMC copre. Colpisci nelle transizioni."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Push ML/MR high as extra attackers. Overwhelm with 6 in attack!",
                "tip_it": "Spingi ML/MR in alto come attaccanti extra. Travolgi con 6 in attacco!"
            }
        }
    },
    {
        "id": "541f",
        "name": "5-4-1 F (Flat)",
        "description_en": "Classic parked bus. 5 defenders + 4 flat midfielders. Counter-attack lethal. Maximum defensive solidity.",
        "description_it": "Bus parcheggiato classico. 5 difensori + 4 centrocampisti piatti. Contropiede letale. Massima solidità difensiva.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST"],
        "category_en": "Defensive",
        "category_it": "Difensiva",
        "strengths_en": ["Maximum defense", "Hard to break down", "Lethal counter", "5 at back"],
        "strengths_it": ["Massima difesa", "Difficile da penetrare", "Contropiede letale", "5 in difesa"],
        "weaknesses_en": ["Very limited attack", "Lone striker", "Can invite pressure"],
        "weaknesses_it": ["Attacco molto limitato", "Attaccante solitario", "Può invitare la pressione"],
        "tactic_type_en": "Ultra Defensive / Bus Parking",
        "tactic_type_it": "Ultra Difensivo / Catenaccio",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "FULL CATENACCIO! 5-4-1 deep and compact. Long balls to lone striker on rare counters.",
                "tip_it": "CATENACCIO TOTALE! 5-4-1 profondo e compatto. Palle lunghe all'attaccante nei rari contropiedi."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Stay organized. Let wing-backs push when safe. Target lone striker.",
                "tip_it": "Resta organizzato. Lascia sovrapporre gli esterni quando è sicuro. Punta l'attaccante solitario."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push wing-backs higher to create. You can be more adventurous.",
                "tip_it": "Spingi gli esterni più in alto per creare. Puoi essere più avventuroso."
            }
        }
    },
    {
        "id": "32221b",
        "name": "3-2-2-2-1 B (Butterfly)",
        "description_en": "Defensive Butterfly formation. Double AMC creates chances for lone striker.",
        "description_it": "Butterfly difensivo. Doppio trequartista crea occasioni per l'attaccante solitario.",
        "positions": ["GK", "DC", "DC", "DC", "MC", "MC", "AMC", "AMC", "ST"],
        "category_en": "Defensive",
        "category_it": "Difensiva",
        "strengths_en": ["Double playmakers", "Compact center", "Counter-attack ready"],
        "strengths_it": ["Doppi registi", "Centro compatto", "Pronto al contropiede"],
        "weaknesses_en": ["No width", "3 CBs exposed", "Needs quality AMCs"],
        "weaknesses_it": ["Nessuna ampiezza", "3 DC esposti", "Richiede AMC di qualità"],
        "tactic_type_en": "Defensive / Creative",
        "tactic_type_it": "Difensivo / Creativo",
        "recommended_tactics": {
            "mentality": "Defensive",
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
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Mixed",
                "focus_passing_it": "Misto",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Stay deep. Double AMC links to ST on counters.",
                "tip_it": "Resta profondo. Doppio AMC collega a ST in contropiede."
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
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Control center with double AMC. Wait for counter opportunities.",
                "tip_it": "Controlla il centro con doppio AMC. Aspetta occasioni di contropiede."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push AMCs forward. Create chances through the middle.",
                "tip_it": "Spingi gli AMC in avanti. Crea occasioni dal centro."
            }
        }
    },
    {
        "id": "3n2221b",
        "name": "3N-2-2-2-1 B (Butterfly 3N)",
        "description_en": "Butterfly with 3 narrow defenders and double DMC. Great against formations with 3 DCs.",
        "description_it": "Butterfly 3 difensori. Doppio DMC. Ottimo contro schemi con 3 DC.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "DMC", "MC", "MC", "AML", "AMR", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["Double DMC shield", "Width with AML/AMR", "Counter 3DC formations"],
        "strengths_it": ["Doppio scudo DMC", "Ampiezza con AML/AMR", "Contrasta formazioni 3DC"],
        "weaknesses_en": ["3 narrow CBs", "Needs quality DMCs", "Can be exposed on flanks"],
        "weaknesses_it": ["3 DC stretti", "Richiede DMC di qualità", "Può essere esposta sulle fasce"],
        "tactic_type_en": "Attacking / Anti-3DC",
        "tactic_type_it": "Attaccante / Anti-3DC",
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
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Double DMC shields 3 CBs. Counter through AML/AMR to ST.",
                "tip_it": "Doppio DMC protegge i 3 DC. Contropiede tramite AML/AMR verso ST."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Balance with double DMC. Use width with AML/AMR.",
                "tip_it": "Equilibrio con doppio DMC. Usa l'ampiezza con AML/AMR."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Push AML/AMR high. Overwhelm with width and pace!",
                "tip_it": "Spingi AML/AMR in alto. Travolgi con ampiezza e velocità!"
            }
        }
    },
    {
        "id": "4141",
        "name": "4-1-4-1",
        "description_en": "Very balanced formation. DMC shields defense while 4 wide midfielders provide width and creativity.",
        "description_it": "Molto bilanciato. Buona copertura in centro e ali. DMC protegge la difesa.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MR", "MC", "MC", "ML", "ST"],
        "category_en": "Balanced",
        "category_it": "Bilanciata",
        "strengths_en": ["Defensive shield", "Wide midfield", "Balanced structure", "Flexible"],
        "strengths_it": ["Scudo difensivo", "Centrocampo ampio", "Struttura equilibrata", "Flessibile"],
        "weaknesses_en": ["Lone striker", "Pivot can be overloaded", "Needs quality DMC"],
        "weaknesses_it": ["Attaccante solitario", "Pivot può essere sovraccaricato", "Richiede DMC di qualità"],
        "tactic_type_en": "Balanced / Defensive",
        "tactic_type_it": "Bilanciato / Difensivo",
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
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "DMC protects the back 4. Use width on counters to find the lone striker.",
                "tip_it": "Il DMC protegge la difesa a 4. Usa l'ampiezza nei contropiedi per trovare l'attaccante."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Balanced approach. Use the width of ML/MR to stretch their defense.",
                "tip_it": "Approccio bilanciato. Usa l'ampiezza di ML/MR per allargare la loro difesa."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Push wide midfielders high. DMC provides cover while you dominate.",
                "tip_it": "Spingi gli esterni alti. Il DMC copre mentre dominate."
            }
        }
    },
    {
        "id": "433",
        "name": "4-3-3",
        "description_en": "Attacking formation with 3 forwards. ★ Red arrows on AML, AMR, ST. 3 attackers press high, MCs fall back in defense.",
        "description_it": "Formazione offensiva con 3 attaccanti. ★ Frecce rosse su AML, AMR, ST. 3 attaccanti, MC rientrano in difesa.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "MC", "AML", "ST", "AMR"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["High pressing", "Width in attack", "Creative midfield", "Overloads flanks"],
        "strengths_it": ["Pressing alto", "Ampiezza in attacco", "Centrocampo creativo", "Sovraccarica le fasce"],
        "weaknesses_en": ["Vulnerable to counters", "Midfield can be overrun", "3 MCs must work hard"],
        "weaknesses_it": ["Vulnerabile ai contropiedi", "Centrocampo può essere sopraffatto", "3 MC devono lavorare duro"],
        "tactic_type_en": "High Press / Attacking",
        "tactic_type_it": "Pressing Alto / Attaccante",
        "arrows": "★ AML↑ AMR↑ ST↑",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Man-to-Man",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Don't overcommit. Use wingers to stretch their defense on counters.",
                "tip_it": "Non esporti troppo. Usa le ali per allargare la difesa in contropiede."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": True,
                "tip_en": "Press high and dominate flanks. Your wingers are key to breaking them.",
                "tip_it": "Pressa alto e domina le fasce. Le tue ali sono la chiave per sfondare."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Full attack mode! Press relentlessly and overload their half.",
                "tip_it": "Attacco totale! Pressa senza sosta e sovraccarica la loro metà campo."
            }
        }
    },
    {
        "id": "53n2",
        "name": "5-3N-2",
        "description_en": "5 defenders + 3 central MCs. Very solid against wing attacks.",
        "description_it": "5 difensori + 3 MC centrali. Solido contro ali.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "MC", "MC", "MC", "ST", "ST"],
        "category_en": "Defensive",
        "category_it": "Difensiva",
        "strengths_en": ["5 defenders", "Central control", "Two strikers", "Hard to break"],
        "strengths_it": ["5 difensori", "Controllo centrale", "Due attaccanti", "Difficile da sfondare"],
        "weaknesses_en": ["No width", "Wing-backs must overlap", "Lacks creativity"],
        "weaknesses_it": ["Nessuna ampiezza", "Gli esterni devono sovrapporre", "Manca creatività"],
        "tactic_type_en": "Ultra Defensive / Central",
        "tactic_type_it": "Ultra Difensivo / Centrale",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Through the Middle",
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
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "5 defenders block everything. Long balls to striker duo on counters.",
                "tip_it": "5 difensori bloccano tutto. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Stay deep and organized. Wing-backs push when safe.",
                "tip_it": "Resta profondo e organizzato. Gli esterni spingono quando è sicuro."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Wing-backs push high. Use width to create for strikers.",
                "tip_it": "Gli esterni spingono in alto. Usa l'ampiezza per creare per gli attaccanti."
            }
        }
    },
    {
        "id": "343",
        "name": "3-4-3",
        "description_en": "Ultra-attacking with 3 attackers and wide midfield. Good against 4-2-2-2 H. Overloads wide midfield.",
        "description_it": "Ultra-offensiva con 3 attaccanti e centrocampo ampio. Contro 4-2-2-2 H. Sovraffolla il centrocampo largo.",
        "positions": ["GK", "DC", "DC", "DC", "MR", "MC", "MC", "ML", "AML", "ST", "AMR"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["3 attackers", "Width", "Pressing intensity", "Overwhelming offense"],
        "strengths_it": ["3 attaccanti", "Ampiezza", "Intensità del pressing", "Attacco travolgente"],
        "weaknesses_en": ["3 CBs only", "Vulnerable to counters", "High stamina needed"],
        "weaknesses_it": ["Solo 3 DC", "Vulnerabile ai contropiedi", "Richiede alta resistenza"],
        "tactic_type_en": "All-Out Attack",
        "tactic_type_it": "Attacco Totale",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "High",
            "tackling": "Normal",
            "marking": "Man-to-Man",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "RISKY! Use only if behind. Protect the 3 CBs on counters.",
                "tip_it": "RISCHIOSO! Usa solo se in svantaggio. Proteggi i 3 DC nei contropiedi."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": True,
                "tip_en": "Attack is the best defense. Press high and force errors.",
                "tip_it": "L'attacco è la miglior difesa. Pressa alto e forza errori."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Destroy them! Full attack with 7 players forward!",
                "tip_it": "Distruggili! Attacco totale con 7 giocatori in avanti!"
            }
        }
    },
    {
        "id": "3w2dmc3w11ml",
        "name": "3W-2DMC-3W-1-1 ML (Maple Leaf)",
        "description_en": "Maple Leaf formation. Wide AML/AMR with AMC as playmaker. Double DMC shield. Against 4-1-3W-2.",
        "description_it": "Maple Leaf. AML/AMR larghi, AMC trequartista. Doppio DMC schermo. Contro 4-1-3W-2.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "DMC", "AML", "AMC", "AMR", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["Double DMC shield", "Wide AML/AMR", "Creative AMC", "Flexible"],
        "strengths_it": ["Doppio scudo DMC", "AML/AMR larghi", "AMC creativo", "Flessibile"],
        "weaknesses_en": ["3 CBs exposed", "Complex to execute", "Needs quality players"],
        "weaknesses_it": ["3 DC esposti", "Complessa da eseguire", "Richiede giocatori di qualità"],
        "tactic_type_en": "Attacking / Creative",
        "tactic_type_it": "Attaccante / Creativo",
        "recommended_tactics": {
            "mentality": "Attacking",
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
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Double DMC protects. Counter through wide AML/AMR to ST.",
                "tip_it": "Doppio DMC protegge. Contropiede tramite AML/AMR larghi verso ST."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "AMC orchestrates. Use wide AML/AMR to create for ST.",
                "tip_it": "L'AMC orchestra. Usa AML/AMR larghi per creare per ST."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "Full creative attack! AMC + wide players overwhelm!",
                "tip_it": "Attacco creativo totale! AMC + esterni travolgono!"
            }
        }
    },
    {
        "id": "3w2dmc3n11tower",
        "name": "3W-2DMC-3N-1-1 Tower (Eiffel Tower)",
        "description_en": "Tower/Eiffel Tower formation. Two screening DMCs, AMC is the offensive tower.",
        "description_it": "Tower: due DMC schermo, AMC torre offensiva.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "DMC", "AML", "AMC", "AMR", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["Double DMC screen", "AMC as tower", "Creative play", "Solid base"],
        "strengths_it": ["Doppio schermo DMC", "AMC come torre", "Gioco creativo", "Base solida"],
        "weaknesses_en": ["3 CBs exposed", "Complex", "Needs quality AMC"],
        "weaknesses_it": ["3 DC esposti", "Complessa", "Richiede AMC di qualità"],
        "tactic_type_en": "Attacking / Tower Style",
        "tactic_type_it": "Attaccante / Stile Torre",
        "recommended_tactics": {
            "mentality": "Normal",
            "focus_passing": "Through the Middle",
            "passing_style": "Short",
            "counter_attack": False,
            "pressing": "Normal",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "DMC duo shields. AMC links to ST on quick counters.",
                "tip_it": "Duo DMC protegge. AMC collega a ST in contropiedi veloci."
            },
            "equal": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "Normal",
                "pressing_it": "Normale",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "AMC is the tower. Feed him and let him create for ST.",
                "tip_it": "L'AMC è la torre. Servilo e lascialo creare per ST."
            },
            "weak": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push AMC high. Let the tower dominate in their half!",
                "tip_it": "Spingi l'AMC in alto. Lascia la torre dominare nella loro metà!"
            }
        }
    },
    {
        "id": "51dmc22",
        "name": "5-1DMC-2-2",
        "description_en": "5 defenders + DMC screen. Against 4-1-3W-1-1 formations.",
        "description_it": "5 difensori + DMC schermo. Contro 4-1-3W-1-1.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "DMC", "AML", "AMR", "ST", "ST"],
        "category_en": "Defensive",
        "category_it": "Difensiva",
        "strengths_en": ["5 defenders", "DMC shield", "Two strikers", "Counter ready"],
        "strengths_it": ["5 difensori", "Scudo DMC", "Due attaccanti", "Pronto al contropiede"],
        "weaknesses_en": ["Very defensive", "Limited midfield", "AML/AMR isolated"],
        "weaknesses_it": ["Molto difensiva", "Centrocampo limitato", "AML/AMR isolati"],
        "tactic_type_en": "Ultra Defensive / Counter",
        "tactic_type_it": "Ultra Difensivo / Contropiede",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "6 defenders! Long balls to striker duo on rare counters.",
                "tip_it": "6 difensori! Palle lunghe alla coppia d'attacco nei rari contropiedi."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Stay deep. Use AML/AMR on counters to find strikers.",
                "tip_it": "Resta profondo. Usa AML/AMR in contropiede per trovare gli attaccanti."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push AML/AMR high. Create for the striker duo.",
                "tip_it": "Spingi AML/AMR in alto. Crea per la coppia d'attacco."
            }
        }
    },
    {
        "id": "5212x",
        "name": "5-2-1-2 X (X-Style)",
        "description_en": "X-Style with DML/DMR. Against 5-2-1-2 formations.",
        "description_it": "X-Style con DML/DMR. Contro 5-2-1-2.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "DML", "DMR", "AMC", "ST", "ST"],
        "category_en": "Defensive",
        "category_it": "Difensiva",
        "strengths_en": ["5 defenders", "DML/DMR coverage", "Counter ready", "Hard to break"],
        "strengths_it": ["5 difensori", "Copertura DML/DMR", "Pronto al contropiede", "Difficile da sfondare"],
        "weaknesses_en": ["Very defensive", "Limited creativity", "Needs fit DML/DMR"],
        "weaknesses_it": ["Molto difensiva", "Creatività limitata", "Richiede DML/DMR in forma"],
        "tactic_type_en": "Ultra Defensive / X-Style",
        "tactic_type_it": "Ultra Difensivo / X-Style",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Through the Middle",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Hard",
            "marking": "Zonal",
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Full catenaccio! DML/DMR block midfield. Long to strikers.",
                "tip_it": "Catenaccio totale! DML/DMR bloccano il centrocampo. Lungo agli attaccanti."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Stay organized. AMC links to strikers on counters.",
                "tip_it": "Resta organizzato. AMC collega agli attaccanti in contropiede."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Through the Middle",
                "focus_passing_it": "Per il centro",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push DML/DMR up. AMC orchestrates attacks to strikers.",
                "tip_it": "Spingi DML/DMR in alto. AMC orchestra attacchi verso gli attaccanti."
            }
        }
    },
    {
        "id": "522amlamr1",
        "name": "5-2-2(AML-AMR)-1",
        "description_en": "5 defenders with high wings. Against 4-2N-1-2W-1 formations.",
        "description_it": "5 difensori con ali alte. Contro 4-2N-1-2W-1.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "MC", "MC", "AML", "AMR", "ST"],
        "category_en": "Defensive",
        "category_it": "Difensiva",
        "strengths_en": ["5 defenders", "High AML/AMR", "Counter ready", "Solid base"],
        "strengths_it": ["5 difensori", "AML/AMR alti", "Pronto al contropiede", "Base solida"],
        "weaknesses_en": ["Lone striker", "Limited creativity", "AML/AMR must track back"],
        "weaknesses_it": ["Attaccante solitario", "Creatività limitata", "AML/AMR devono rientrare"],
        "tactic_type_en": "Defensive / Wide Counter",
        "tactic_type_it": "Difensivo / Contropiede Largo",
        "recommended_tactics": {
            "mentality": "Defensive",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Long",
            "counter_attack": True,
            "pressing": "Low",
            "tackling": "Easy",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Hard Defending",
                "mentality_it": "Molto Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "5 at back tight. Long balls to AML/AMR then to ST.",
                "tip_it": "5 in difesa stretti. Palle lunghe ad AML/AMR poi a ST."
            },
            "equal": {
                "mentality": "Defensive",
                "mentality_it": "Difensivo",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Stay compact. Use AML/AMR pace on counters.",
                "tip_it": "Resta compatto. Usa la velocità di AML/AMR in contropiede."
            },
            "weak": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Push AML/AMR very high. Create for lone striker.",
                "tip_it": "Spingi AML/AMR molto in alto. Crea per l'attaccante solitario."
            }
        }
    },
    {
        "id": "4131w1",
        "name": "4-1-3-1W-1",
        "description_en": "Skewed winger formation. AMR (or AML) on same side as ST. Against 3-4-1-2 (defensive weakness).",
        "description_it": "Ala skewata stesso lato del ST. Contro 3-4-1-2 (debolezza difensiva).",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MC", "MC", "MC", "AMR", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["Skewed attack", "Overload one side", "Creative midfield", "Exploits weak flanks"],
        "strengths_it": ["Attacco skewato", "Sovraccarica un lato", "Centrocampo creativo", "Sfrutta fianchi deboli"],
        "weaknesses_en": ["Unbalanced", "Needs quality AMR", "Exposed on opposite flank"],
        "weaknesses_it": ["Sbilanciata", "Richiede AMR di qualità", "Esposta sul fianco opposto"],
        "tactic_type_en": "Attacking / Skewed",
        "tactic_type_it": "Attaccante / Skewata",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Right Flank",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "Low",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Right Flank",
                "focus_passing_it": "Fascia destra",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Easy",
                "tackling_it": "Facile",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Counter through skewed side. AMR + ST combo on breaks.",
                "tip_it": "Contropiede dal lato skewato. Combo AMR + ST nelle ripartenze."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Right Flank",
                "focus_passing_it": "Fascia destra",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "Low",
                "pressing_it": "Basso",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Overload right side. AMR and ST create overload.",
                "tip_it": "Sovraccarica il lato destro. AMR e ST creano superiorità."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Right Flank",
                "focus_passing_it": "Fascia destra",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "All-out attack on right side! 2nd half switch to high pressing.",
                "tip_it": "Attacco totale sul lato destro! Nel 2°T passa a pressing alto."
            }
        }
    },
    {
        "id": "3n52v",
        "name": "3N-5-2 V",
        "description_en": "3 DCs + 5 midfielders with high AML/AMR. Effective against parked bus formations.",
        "description_it": "3 DC + 5 MF con ali alte. Efficace contro bus parcheggiato.",
        "positions": ["GK", "DC", "DC", "DC", "MC", "MC", "MC", "AML", "AMR", "ST", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["High wingers", "Midfield control", "Two strikers", "Breaks parked bus"],
        "strengths_it": ["Ali alte", "Controllo centrocampo", "Due attaccanti", "Sfonda il catenaccio"],
        "weaknesses_en": ["3 CBs exposed", "No full-backs", "High stamina needed"],
        "weaknesses_it": ["3 DC esposti", "Nessun terzino", "Richiede alta resistenza"],
        "tactic_type_en": "Attacking / Anti-Parked Bus",
        "tactic_type_it": "Attaccante / Anti-Catenaccio",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": True,
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
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "Protect 3 CBs. Use AML/AMR pace on counters to strikers.",
                "tip_it": "Proteggi i 3 DC. Usa la velocità di AML/AMR in contropiede verso gli attaccanti."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": True,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Use width to stretch parked buses. AML/AMR + 2 STs overload.",
                "tip_it": "Usa l'ampiezza per allargare il catenaccio. AML/AMR + 2 ST sovraccaricano."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "All-out attack! 7 players forward will destroy them!",
                "tip_it": "Attacco totale! 7 giocatori in avanti li distruggeranno!"
            }
        }
    },
    {
        "id": "43n2w1",
        "name": "4-3N-2W-1",
        "description_en": "3 central MCs + high AML/AMR. Very common at high levels.",
        "description_it": "3 MC + AML/AMR alti. Molto diffusa ai livelli alti.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "MC", "AML", "AMR", "ST"],
        "category_en": "Attacking",
        "category_it": "Attaccante",
        "strengths_en": ["Central control", "High wingers", "Popular at high levels", "Flexible"],
        "strengths_it": ["Controllo centrale", "Ali alte", "Popolare ai livelli alti", "Flessibile"],
        "weaknesses_en": ["Lone striker", "Needs quality MCs", "Can be exposed on counters"],
        "weaknesses_it": ["Attaccante solitario", "Richiede MC di qualità", "Può essere esposta ai contropiedi"],
        "tactic_type_en": "Attacking / High Level Meta",
        "tactic_type_it": "Attaccante / Meta Alto Livello",
        "recommended_tactics": {
            "mentality": "Attacking",
            "focus_passing": "Down Both Flanks",
            "passing_style": "Mixed",
            "counter_attack": False,
            "pressing": "Normal",
            "tackling": "Normal",
            "marking": "Zonal",
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": "Normal",
                "mentality_it": "Normale",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Long",
                "passing_style_it": "Lungo",
                "counter_attack": True,
                "pressing": "Medium",
                "pressing_it": "Medio",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": True,
                "tip_en": "3 MCs control center. AML/AMR break on counters to ST.",
                "tip_it": "3 MC controllano il centro. AML/AMR sfondano in contropiede verso ST."
            },
            "equal": {
                "mentality": "Attacking",
                "mentality_it": "Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Mixed",
                "passing_style_it": "Misto",
                "counter_attack": False,
                "pressing": "Normal",
                "pressing_it": "Normale",
                "tackling": "Normal",
                "tackling_it": "Normale",
                "marking": "Zonal",
                "marking_it": "Zonale",
                "offside_trap": False,
                "tip_en": "Dominate midfield with 3 MCs. AML/AMR create for lone ST.",
                "tip_it": "Domina il centrocampo con 3 MC. AML/AMR creano per ST solitario."
            },
            "weak": {
                "mentality": "Hard Attacking",
                "mentality_it": "Molto Attaccante",
                "focus_passing": "Down Both Flanks",
                "focus_passing_it": "Per entrambe le fasce",
                "passing_style": "Short",
                "passing_style_it": "Corti",
                "counter_attack": False,
                "pressing": "High",
                "pressing_it": "Alto",
                "tackling": "Hard",
                "tackling_it": "Duro",
                "marking": "Man-to-Man",
                "marking_it": "Uomo a Uomo",
                "offside_trap": False,
                "tip_en": "All-out attack! Push all 6 attackers forward!",
                "tip_it": "Attacco totale! Spingi tutti i 6 attaccanti in avanti!"
            }
        }
    }
]

# ==================== COUNTER TACTICS DATA (EXPANDED from PDF) ====================

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
