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
        "id": '442c',
        "name": '4-4-2 C (Classic)',
        "description_en": 'Classic balanced formation. Strong in both defense and attack with 4 defenders, 4 midfielders, and 2 strikers. One of the oldest and most reliable formations in football.',
        "description_it": 'Formazione bilanciata classica. Forte in ampiezza. 4 difensori, 4 centrocampisti e 2 attaccanti.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'MR', 'MC', 'MC', 'ML', 'ST', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Balanced', 'Good width', 'Partnership up front', 'Simple to execute'],
        "strengths_it": ['Equilibrata', 'Buona ampiezza', 'Partnership in attacco', 'Semplice da eseguire'],
        "weaknesses_en": ['Can be outnumbered in midfield', 'Requires fit wingers'],
        "weaknesses_it": ['Può essere superata numericamente a centrocampo', 'Richiede ali in forma'],
        "tactic_type_en": 'Balanced',
        "tactic_type_it": 'Bilanciato',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Short',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Stay compact and let them come. Use long balls to your strikers on counter.',
                "tip_it": 'Resta compatto e lasciali venire. Usa palle lunghe agli attaccanti in contropiede.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Play your natural game. Use width and crosses to find your two strikers.',
                "tip_it": "Gioca il tuo gioco naturale. Usa l'ampiezza e i cross per trovare i due attaccanti."
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Dominate with high pressing and quick passing. Overwhelm their defense with numbers.',
                "tip_it": 'Domina con pressing alto e passaggi veloci. Travolgi la loro difesa con i numeri.'
            }
        }
    },
    {
        "id": '41212nd',
        "name": '4-1-2-1-2 ND (Narrow Diamond)',
        "description_en": 'Narrow diamond midfield formation. Strong through the center with DMC protecting defense and AMC linking play. Flanks are vulnerable - attack down the wings against this.',
        "description_it": 'Diamond stretto. DMC protegge la difesa e AMC collega il gioco. I fianchi sono vulnerabili: attacca sulle ali contro questa formazione.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'DMC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Central dominance', 'Creative #10', 'Two striker partnership', 'Good passing lanes'],
        "strengths_it": ['Dominio centrale', 'Trequartista creativo', 'Partnership di due attaccanti', 'Buone linee di passaggio'],
        "weaknesses_en": ['No natural wingers', 'Exposed flanks', 'Requires box-to-box midfielders'],
        "weaknesses_it": ['Nessuna ala naturale', 'Fianchi esposti', 'Richiede centrocampisti box-to-box'],
        "tactic_type_en": 'Possession / Central Attack',
        "tactic_type_it": 'Possesso / Attacco Centrale',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Short',
            "counter_attack": False,
            "pressing": 'Normal',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'DMC shields the back 4. Long balls to striker partnership on counters.',
                "tip_it": "Il DMC protegge la difesa a 4. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Control the center and let AMC create for the 2 strikers. Be patient.',
                "tip_it": "Controlla il centro e lascia che l'AMC crei per i 2 attaccanti. Sii paziente."
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Dominate the center completely. Your AMC should feast on their weak midfield.',
                "tip_it": 'Domina il centro completamente. Il tuo AMC deve banchettare sul loro centrocampo debole.'
            }
        }
    },
    {
        "id": '41212wd',
        "name": '4-1-2-1-2 WD (Wide Diamond)',
        "description_en": 'Wide diamond with high AML/AMR. More width than narrow diamond but vulnerable in the center.',
        "description_it": 'Diamond largo. AML/AMR alti. Vulnerabile nel centro.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'DMC', 'AML', 'AMR', 'AMC', 'ST', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Width in attack', 'Creative AMC', 'Two strikers', 'Flexible wingers'],
        "strengths_it": ['Ampiezza in attacco', 'AMC creativo', 'Due attaccanti', 'Ali flessibili'],
        "weaknesses_en": ['Vulnerable center', 'No central midfield', 'Exposed to central attacks'],
        "weaknesses_it": ['Centro vulnerabile', 'Nessun centrocampo centrale', 'Esposta ad attacchi centrali'],
        "tactic_type_en": 'Attacking / Wide',
        "tactic_type_it": 'Attaccante / Largo',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": False,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Stay compact. Use AML/AMR pace on counters to find strikers.',
                "tip_it": 'Resta compatto. Usa la velocità di AML/AMR in contropiede per trovare gli attaccanti.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Use width with AML/AMR. AMC links play between midfield and strikers.',
                "tip_it": "Usa l'ampiezza con AML/AMR. L'AMC collega centrocampo e attaccanti."
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Push AML/AMR high. Overload their flanks with width and crosses.',
                "tip_it": 'Spingi AML/AMR in alto. Sovraccarica le loro fasce con ampiezza e cross.'
            }
        }
    },
    {
        "id": '451v',
        "name": '4-5-1 V-Style',
        "description_en": 'Excellent defensive formation with V-shaped midfield (DMC-2MC-AML-AMR). Perfect counter-attacking setup. META choice against possession teams and narrow diamonds.',
        "description_it": 'Eccellente formazione difensiva con centrocampo a V (DMC-2MC-AML-AMR). Setup perfetto per il contropiede. Scelta META contro squadre di possesso e diamanti stretti.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['Solid 4-man defense', 'Numerical midfield advantage', 'Wide attacks from AML/AMR', 'Counters 4-4-2 perfectly', 'V-shape controls space'],
        "strengths_it": ['Difesa solida a 4', 'Vantaggio numerico a centrocampo', 'Attacchi larghi da AML/AMR', 'Contrasta perfettamente il 4-4-2', 'Forma a V controlla lo spazio'],
        "weaknesses_en": ['Lone striker isolated', 'Requires pace on wings', 'Can be too defensive'],
        "weaknesses_it": ['Attaccante solitario isolato', 'Richiede velocità sulle fasce', 'Può essere troppo difensiva'],
        "tactic_type_en": '★ META 2026 / Counter-Attack',
        "tactic_type_it": '★ META 2026 / Contropiede',
        "arrows": 'DMC↓ AML↑ AMR↑',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensiva',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Sulle Fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "tip_en": 'Park the bus! Let them attack, hit on counter with AML/AMR speed. DMC↓ to shield DCs.',
                "tip_it": 'Parcheggia il bus! Lascia che attacchino, colpisci in contropiede con velocità AML/AMR. DMC↓ per schermare DC.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "tip_en": 'V-shape gives control. Push AML/AMR↑ for attack width. Counter when they overcommit.',
                "tip_it": 'La forma a V dà controllo. Spingi AML/AMR↑ per ampiezza. Contropiede quando si sbilanciano.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Offensiva',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Sulle Fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Dominate wings! DL/DR↑ overlap. AML/AMR become wingers. Overload their flanks.',
                "tip_it": 'Domina le fasce! DL/DR↑ sovrapposizione. AML/AMR diventano ali. Sovraccarica le loro fasce.'
            }
        }
    },
    {
        "id": '451f',
        "name": '4-5-1 F (Flat)',
        "description_en": '5 flat midfielders. Great for counter-attacking and controlling possession. Defensive but lethal on breaks.',
        "description_it": '5 centrocampisti piatti. Buono in contropiede e controllo possesso. Difensivo ma letale nelle ripartenze.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'MR', 'MC', 'MC', 'MC', 'ML', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['5-man midfield', 'Counter-attack', 'Defensive solidity', 'Width control'],
        "strengths_it": ['Centrocampo a 5', 'Contropiede', 'Solidità difensiva', 'Controllo ampiezza'],
        "weaknesses_en": ['Lone striker isolated', 'Limited attack', 'Predictable'],
        "weaknesses_it": ['Attaccante isolato', 'Attacco limitato', 'Prevedibile'],
        "tactic_type_en": 'Counter-Attack / Defensive',
        "tactic_type_it": 'Contropiede / Difensivo',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Mixed',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": '5 flat midfielders block everything. Counter with long balls to lone ST.',
                "tip_it": '5 centrocampisti piatti bloccano tutto. Contropiede con palle lunghe al ST solitario.'
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Control midfield with 5 players. Wait for counter opportunities.',
                "tip_it": 'Controlla il centrocampo con 5 giocatori. Aspetta occasioni di contropiede.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Push wide midfielders up. Use width to create for the lone striker.',
                "tip_it": "Spingi gli esterni in alto. Usa l'ampiezza per creare per l'attaccante solitario."
            }
        }
    },
    {
        "id": '4231',
        "name": '4-2-3-1',
        "description_en": 'Modern tactical formation with 2 MCs and 3 attacking mids behind lone striker. ★ Defensive arrows on 3DC, ML and MR.',
        "description_it": 'Formazione tattica moderna con 2 MC e 3 trequartisti dietro attaccante solitario. ★ Frecce difensive a 3DC, ML e MR.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Defensive stability', 'Creative playmaker', 'Compact midfield', 'Flexible'],
        "strengths_it": ['Stabilità difensiva', 'Regista creativo', 'Centrocampo compatto', 'Flessibile'],
        "weaknesses_en": ['Lone striker isolated', 'Depends heavily on AMC', 'Can lack width'],
        "weaknesses_it": ['Attaccante solitario isolato', "Dipende molto dall'AMC", 'Può mancare ampiezza'],
        "tactic_type_en": 'Balanced / Counter-Attack',
        "tactic_type_it": 'Bilanciato / Contropiede',
        "arrows": '★ DC↓ DL↓ DR↓ ML↓ MR↓',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": '2 MCs protect defense. Use AMC to link play on counter-attacks.',
                "tip_it": "2 MC proteggono la difesa. Usa l'AMC per collegare in contropiede."
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Let AMC orchestrate attacks. Use AML/AMR width to create for the lone striker.',
                "tip_it": "Lascia l'AMC orchestrare gli attacchi. Usa AML/AMR per creare per l'attaccante."
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Push your AML/AMR high. Overload their defense with creative play through AMC.',
                "tip_it": "Spingi AML/AMR in avanti. Sovraccarica la difesa con gioco creativo dall'AMC."
            }
        }
    },
    {
        "id": '4222h',
        "name": '4-2-2-2 H (Hexagon)',
        "description_en": 'Compact Hexagon formation with 2 MCs, 2 AMs, and 2 strikers. ★ Arrows forward on DL, DR, AML, AMR.',
        "description_it": 'Formazione compatta Hexagon con 2 MC, 2 trequartisti e 2 attaccanti. ★ Frecce avanti a DL, DR, AML, AMR.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'MC', 'MC', 'AML', 'AMR', 'ST', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Central control', 'Two partnerships', 'Compact shape', 'Transitions well'],
        "strengths_it": ['Controllo centrale', 'Due partnership', 'Forma compatta', 'Buone transizioni'],
        "weaknesses_en": ['Lacks width', 'No natural wingers', 'Predictable'],
        "weaknesses_it": ['Manca ampiezza', 'Nessuna ala naturale', 'Prevedibile'],
        "tactic_type_en": 'Central / Transition',
        "tactic_type_it": 'Centrale / Transizione',
        "arrows": '★ DL↑ DR↑ AML↑ AMR↑',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Stay compact in center. Use the 2 striker partnership to hold the ball on counters.',
                "tip_it": "Resta compatto al centro. Usa la coppia d'attacco per tenere palla nei contropiedi."
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Control center with compact shape. AML/AMR drift in to support strikers.',
                "tip_it": 'Controlla il centro con la forma compatta. AML/AMR accentrarsi per supportare gli attaccanti.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Overwhelm center! Your 4 central attackers should dominate their midfield.',
                "tip_it": 'Travolgi il centro! I tuoi 4 attaccanti centrali devono dominare il loro centrocampo.'
            }
        }
    },
    {
        "id": '352f',
        "name": '3-5-2 F (Flat)',
        "description_en": "Midfield-dominant with 5 flat midfielders. No full-backs - exploit opponent's free wings against this formation.",
        "description_it": 'Dominante a centrocampo con 5 centrocampisti piatti. Nessun terzino - sfrutta le ali libere del rivale.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'MR', 'MC', 'MC', 'MC', 'ML', 'ST', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Midfield control', 'Numerical advantage in center', 'Partnership up front'],
        "strengths_it": ['Controllo del centrocampo', 'Vantaggio numerico al centro', 'Partnership in attacco'],
        "weaknesses_en": ['Exposed flanks', 'No full-backs', 'Weak against wide formations'],
        "weaknesses_it": ['Fianchi esposti', 'Nessun terzino', 'Debole contro formazioni ampie'],
        "tactic_type_en": 'Attacking / High Press',
        "tactic_type_it": 'Attaccante / Pressing Alto',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Mixed',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Man-to-Man',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": True,
                "tip_en": 'Keep 5 midfielders tight. Counter through striker partnership.',
                "tip_it": "Tieni i 5 centrocampisti stretti. Contropiede attraverso la coppia d'attacco."
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": True,
                "tip_en": 'Dominate midfield with 5 players. ML/MR overlap for width.',
                "tip_it": 'Domina il centrocampo con 5 giocatori. ML/MR sovrappongono per ampiezza.'
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'All-out attack with 7 players forward. Overwhelm their defense!',
                "tip_it": 'Attacco totale con 7 giocatori in avanti. Travolgi la loro difesa!'
            }
        }
    },
    {
        "id": '352v',
        "name": '3-5-2 V (V-Style)',
        "description_en": 'V-style 3-5-2 with high AML/AMR. Effective against crowded midfield but open wings.',
        "description_it": '3-5-2 V-style con AML/AMR alti. Efficace contro centrocampo affollato ma ali scoperte.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['High wingers', 'Midfield control', 'Two strikers', 'Pressing'],
        "strengths_it": ['Ali alte', 'Controllo centrocampo', 'Due attaccanti', 'Pressing'],
        "weaknesses_en": ['Exposed 3 CBs', 'No full-backs', 'Vulnerable on flanks'],
        "weaknesses_it": ['3 DC esposti', 'Nessun terzino', 'Vulnerabile sulle fasce'],
        "tactic_type_en": 'Attacking / Wide High',
        "tactic_type_it": 'Attaccante / Ali Alte',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'High AML/AMR exploit space on counters. Protect 3 CBs.',
                "tip_it": 'AML/AMR alti sfruttano spazi in contropiede. Proteggi i 3 DC.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Use width with AML/AMR. Strike partnership creates chances.',
                "tip_it": "Usa l'ampiezza con AML/AMR. La coppia d'attacco crea occasioni."
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Push AML/AMR very high. Overwhelm with 5 attackers!',
                "tip_it": 'Spingi AML/AMR molto in alto. Travolgi con 5 attaccanti!'
            }
        }
    },
    {
        "id": '3142',
        "name": '3-1-4-2',
        "description_en": 'DMC anchors the midfield with 4 wide midfielders. Strong against 4-3-3 and formations with 3 attackers.',
        "description_it": 'DMC ancora il centrocampo con 4 centrocampisti larghi. Forte contro 4-3-3 e formazioni con 3 attaccanti.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'DMC', 'MR', 'MC', 'MC', 'ML', 'ST', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['DMC protection', 'Wide midfield', 'Two strikers', 'Counter 4-3-3'],
        "strengths_it": ['Protezione DMC', 'Centrocampo ampio', 'Due attaccanti', 'Contrasta 4-3-3'],
        "weaknesses_en": ['3 CBs exposed', 'Needs fit ML/MR', 'Vulnerable to counters'],
        "weaknesses_it": ['3 DC esposti', 'Richiede ML/MR in forma', 'Vulnerabile ai contropiedi'],
        "tactic_type_en": 'Counter-Attack / Anti-433',
        "tactic_type_it": 'Contropiede / Anti-433',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Mixed',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Man-to-Man',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": True,
                "tip_en": 'DMC shields 3 CBs. Long balls to striker partnership on counters.',
                "tip_it": "Il DMC protegge i 3 DC. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": True,
                "tip_en": 'Press high with 4 midfielders. DMC covers. Strike on transitions.',
                "tip_it": 'Pressa alto con 4 centrocampisti. Il DMC copre. Colpisci nelle transizioni.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Push ML/MR high as extra attackers. Overwhelm with 6 in attack!',
                "tip_it": 'Spingi ML/MR in alto come attaccanti extra. Travolgi con 6 in attacco!'
            }
        }
    },
    {
        "id": '541f',
        "name": '5-4-1 F (Flat)',
        "description_en": 'Classic parked bus. 5 defenders + 4 flat midfielders. Counter-attack lethal. Maximum defensive solidity.',
        "description_it": 'Bus parcheggiato classico. 5 difensori + 4 centrocampisti piatti. Contropiede letale. Massima solidità difensiva.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'MR', 'MC', 'MC', 'ML', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['Maximum defense', 'Hard to break down', 'Lethal counter', '5 at back'],
        "strengths_it": ['Massima difesa', 'Difficile da penetrare', 'Contropiede letale', '5 in difesa'],
        "weaknesses_en": ['Very limited attack', 'Lone striker', 'Can invite pressure'],
        "weaknesses_it": ['Attacco molto limitato', 'Attaccante solitario', 'Può invitare la pressione'],
        "tactic_type_en": 'Ultra Defensive / Bus Parking',
        "tactic_type_it": 'Ultra Difensivo / Catenaccio',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'FULL CATENACCIO! 5-4-1 deep and compact. Long balls to lone striker on rare counters.',
                "tip_it": "CATENACCIO TOTALE! 5-4-1 profondo e compatto. Palle lunghe all'attaccante nei rari contropiedi."
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Stay organized. Let wing-backs push when safe. Target lone striker.',
                "tip_it": "Resta organizzato. Lascia sovrapporre gli esterni quando è sicuro. Punta l'attaccante solitario."
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Push wing-backs higher to create. You can be more adventurous.',
                "tip_it": 'Spingi gli esterni più in alto per creare. Puoi essere più avventuroso.'
            }
        }
    },
    {
        "id": '32221b',
        "name": '3-2-2-2-1 B (Butterfly)',
        "description_en": 'Defensive Butterfly formation. Double AMC creates chances for lone striker.',
        "description_it": "Butterfly difensivo. Doppio trequartista crea occasioni per l'attaccante solitario.",
        "positions": ['GK', 'DC', 'DC', 'DC', 'MC', 'MC', 'AMC', 'AMC', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['Double playmakers', 'Compact center', 'Counter-attack ready'],
        "strengths_it": ['Doppi registi', 'Centro compatto', 'Pronto al contropiede'],
        "weaknesses_en": ['No width', '3 CBs exposed', 'Needs quality AMCs'],
        "weaknesses_it": ['Nessuna ampiezza', '3 DC esposti', 'Richiede AMC di qualità'],
        "tactic_type_en": 'Defensive / Creative',
        "tactic_type_it": 'Difensivo / Creativo',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Mixed',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Stay deep. Double AMC links to ST on counters.',
                "tip_it": 'Resta profondo. Doppio AMC collega a ST in contropiede.'
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Control center with double AMC. Wait for counter opportunities.',
                "tip_it": 'Controlla il centro con doppio AMC. Aspetta occasioni di contropiede.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Push AMCs forward. Create chances through the middle.',
                "tip_it": 'Spingi gli AMC in avanti. Crea occasioni dal centro.'
            }
        }
    },
    {
        "id": '3n2221b',
        "name": '3N-2-2-2-1 B (Butterfly 3N)',
        "description_en": 'Butterfly with 3 narrow defenders and double DMC. Great against formations with 3 DCs.',
        "description_it": 'Butterfly 3 difensori. Doppio DMC. Ottimo contro schemi con 3 DC.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Double DMC shield', 'Width with AML/AMR', 'Counter 3DC formations'],
        "strengths_it": ['Doppio scudo DMC', 'Ampiezza con AML/AMR', 'Contrasta formazioni 3DC'],
        "weaknesses_en": ['3 narrow CBs', 'Needs quality DMCs', 'Can be exposed on flanks'],
        "weaknesses_it": ['3 DC stretti', 'Richiede DMC di qualità', 'Può essere esposta sulle fasce'],
        "tactic_type_en": 'Attacking / Anti-3DC',
        "tactic_type_it": 'Attaccante / Anti-3DC',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Double DMC shields 3 CBs. Counter through AML/AMR to ST.',
                "tip_it": 'Doppio DMC protegge i 3 DC. Contropiede tramite AML/AMR verso ST.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Balance with double DMC. Use width with AML/AMR.',
                "tip_it": "Equilibrio con doppio DMC. Usa l'ampiezza con AML/AMR."
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Push AML/AMR high. Overwhelm with width and pace!',
                "tip_it": 'Spingi AML/AMR in alto. Travolgi con ampiezza e velocità!'
            }
        }
    },
    {
        "id": '4141',
        "name": '4-1-4-1',
        "description_en": 'Classic defensive formation with single DMC shield. 4-man backline, 4 midfielders, 1 striker. Great for controlling games and counter-attacking against 4-4-2.',
        "description_it": 'Formazione difensiva classica con singolo scudo DMC. Linea difensiva a 4, 4 centrocampisti, 1 attaccante. Ottima per controllare le partite e contropiede contro 4-4-2.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MC', 'MR', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['Compact and solid', 'DMC protects defense', 'Wide coverage', 'Easy live adjustments', 'Counters 4-4-2 effectively'],
        "strengths_it": ['Compatta e solida', 'DMC protegge la difesa', 'Copertura ampia', 'Facili aggiustamenti live', 'Contrasta efficacemente il 4-4-2'],
        "weaknesses_en": ['Lone striker problem', 'Can lack creativity', 'MC overworked'],
        "weaknesses_it": ['Problema attaccante solitario', 'Può mancare creatività', 'MC sovraccaricati'],
        "tactic_type_en": 'META 2026 / Solid Defense',
        "tactic_type_it": 'META 2026 / Difesa Solida',
        "arrows": 'DMC↓',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensiva',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Sulle Fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": False,
                "tip_en": 'Defend deep! DMC↓ always. ML/MR track back. Quick long balls to ST on counter.',
                "tip_it": 'Difendi basso! DMC↓ sempre. ML/MR rientrano. Lanci lunghi rapidi a ST in contropiede.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": False,
                "tip_en": 'Control the game. DMC anchors defense. Push MC forward if winning.',
                "tip_it": 'Controlla la partita. DMC ancora la difesa. Spingi MC avanti se in vantaggio.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Offensiva',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il Centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Push everyone! DMC becomes MC, ML/MR become AML/AMR. Suffocate them.',
                "tip_it": 'Spingi tutti! DMC diventa MC, ML/MR diventano AML/AMR. Soffocali.'
            }
        }
    },
    {
        "id": '433',
        "name": '4-3-3',
        "description_en": 'Attacking formation with 3 forwards. ★ Red arrows on AML, AMR, ST. 3 attackers press high, MCs fall back in defense.',
        "description_it": 'Formazione offensiva con 3 attaccanti. ★ Frecce rosse su AML, AMR, ST. 3 attaccanti, MC rientrano in difesa.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'MC', 'MC', 'MC', 'AML', 'ST', 'AMR'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['High pressing', 'Width in attack', 'Creative midfield', 'Overloads flanks'],
        "strengths_it": ['Pressing alto', 'Ampiezza in attacco', 'Centrocampo creativo', 'Sovraccarica le fasce'],
        "weaknesses_en": ['Vulnerable to counters', 'Midfield can be overrun', '3 MCs must work hard'],
        "weaknesses_it": ['Vulnerabile ai contropiedi', 'Centrocampo può essere sopraffatto', '3 MC devono lavorare duro'],
        "tactic_type_en": 'High Press / Attacking',
        "tactic_type_it": 'Pressing Alto / Attaccante',
        "arrows": '★ AML↑ AMR↑ ST↑',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": False,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Man-to-Man',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": "Don't overcommit. Use wingers to stretch their defense on counters.",
                "tip_it": 'Non esporti troppo. Usa le ali per allargare la difesa in contropiede.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": True,
                "tip_en": 'Press high and dominate flanks. Your wingers are key to breaking them.',
                "tip_it": 'Pressa alto e domina le fasce. Le tue ali sono la chiave per sfondare.'
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Full attack mode! Press relentlessly and overload their half.',
                "tip_it": 'Attacco totale! Pressa senza sosta e sovraccarica la loro metà campo.'
            }
        }
    },
    {
        "id": '53n2',
        "name": '5-3N-2',
        "description_en": '5 defenders + 3 central MCs. Very solid against wing attacks.',
        "description_it": '5 difensori + 3 MC centrali. Solido contro ali.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'MC', 'MC', 'MC', 'ST', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['5 defenders', 'Central control', 'Two strikers', 'Hard to break'],
        "strengths_it": ['5 difensori', 'Controllo centrale', 'Due attaccanti', 'Difficile da sfondare'],
        "weaknesses_en": ['No width', 'Wing-backs must overlap', 'Lacks creativity'],
        "weaknesses_it": ['Nessuna ampiezza', 'Gli esterni devono sovrapporre', 'Manca creatività'],
        "tactic_type_en": 'Ultra Defensive / Central',
        "tactic_type_it": 'Ultra Difensivo / Centrale',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": '5 defenders block everything. Long balls to striker duo on counters.',
                "tip_it": "5 difensori bloccano tutto. Palle lunghe alla coppia d'attacco in contropiede."
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Stay deep and organized. Wing-backs push when safe.',
                "tip_it": 'Resta profondo e organizzato. Gli esterni spingono quando è sicuro.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Wing-backs push high. Use width to create for strikers.',
                "tip_it": "Gli esterni spingono in alto. Usa l'ampiezza per creare per gli attaccanti."
            }
        }
    },
    {
        "id": '343',
        "name": '3-4-3',
        "description_en": 'Ultra-attacking with 3 attackers and wide midfield. Good against 4-2-2-2 H. Overloads wide midfield.',
        "description_it": 'Ultra-offensiva con 3 attaccanti e centrocampo ampio. Contro 4-2-2-2 H. Sovraffolla il centrocampo largo.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'MR', 'MC', 'MC', 'ML', 'AML', 'ST', 'AMR'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['3 attackers', 'Width', 'Pressing intensity', 'Overwhelming offense'],
        "strengths_it": ['3 attaccanti', 'Ampiezza', 'Intensità del pressing', 'Attacco travolgente'],
        "weaknesses_en": ['3 CBs only', 'Vulnerable to counters', 'High stamina needed'],
        "weaknesses_it": ['Solo 3 DC', 'Vulnerabile ai contropiedi', 'Richiede alta resistenza'],
        "tactic_type_en": 'All-Out Attack',
        "tactic_type_it": 'Attacco Totale',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Short',
            "counter_attack": False,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Man-to-Man',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'RISKY! Use only if behind. Protect the 3 CBs on counters.',
                "tip_it": 'RISCHIOSO! Usa solo se in svantaggio. Proteggi i 3 DC nei contropiedi.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": True,
                "tip_en": 'Attack is the best defense. Press high and force errors.',
                "tip_it": "L'attacco è la miglior difesa. Pressa alto e forza errori."
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Destroy them! Full attack with 7 players forward!',
                "tip_it": 'Distruggili! Attacco totale con 7 giocatori in avanti!'
            }
        }
    },
    {
        "id": '3w2dmc3w11ml',
        "name": '3W-2DMC-3W-1-1 ML (Maple Leaf)',
        "description_en": 'Maple Leaf formation. Wide AML/AMR with AMC as playmaker. Double DMC shield. Against 4-1-3W-2.',
        "description_it": 'Maple Leaf. AML/AMR larghi, AMC trequartista. Doppio DMC schermo. Contro 4-1-3W-2.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'AML', 'AMC', 'AMR', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Double DMC shield', 'Wide AML/AMR', 'Creative AMC', 'Flexible'],
        "strengths_it": ['Doppio scudo DMC', 'AML/AMR larghi', 'AMC creativo', 'Flessibile'],
        "weaknesses_en": ['3 CBs exposed', 'Complex to execute', 'Needs quality players'],
        "weaknesses_it": ['3 DC esposti', 'Complessa da eseguire', 'Richiede giocatori di qualità'],
        "tactic_type_en": 'Attacking / Creative',
        "tactic_type_it": 'Attaccante / Creativo',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Double DMC protects. Counter through wide AML/AMR to ST.',
                "tip_it": 'Doppio DMC protegge. Contropiede tramite AML/AMR larghi verso ST.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'AMC orchestrates. Use wide AML/AMR to create for ST.',
                "tip_it": "L'AMC orchestra. Usa AML/AMR larghi per creare per ST."
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Full creative attack! AMC + wide players overwhelm!',
                "tip_it": 'Attacco creativo totale! AMC + esterni travolgono!'
            }
        }
    },
    {
        "id": '3w2dmc3n11tower',
        "name": '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
        "description_en": 'Tower/Eiffel Tower formation. Two screening DMCs, AMC is the offensive tower.',
        "description_it": 'Tower: due DMC schermo, AMC torre offensiva.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'AML', 'AMC', 'AMR', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Double DMC screen', 'AMC as tower', 'Creative play', 'Solid base'],
        "strengths_it": ['Doppio schermo DMC', 'AMC come torre', 'Gioco creativo', 'Base solida'],
        "weaknesses_en": ['3 CBs exposed', 'Complex', 'Needs quality AMC'],
        "weaknesses_it": ['3 DC esposti', 'Complessa', 'Richiede AMC di qualità'],
        "tactic_type_en": 'Attacking / Tower Style',
        "tactic_type_it": 'Attaccante / Stile Torre',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Short',
            "counter_attack": False,
            "pressing": 'Normal',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'DMC duo shields. AMC links to ST on quick counters.',
                "tip_it": 'Duo DMC protegge. AMC collega a ST in contropiedi veloci.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'AMC is the tower. Feed him and let him create for ST.',
                "tip_it": "L'AMC è la torre. Servilo e lascialo creare per ST."
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Push AMC high. Let the tower dominate in their half!',
                "tip_it": "Spingi l'AMC in alto. Lascia la torre dominare nella loro metà!"
            }
        }
    },
    {
        "id": '51dmc22',
        "name": '5-1DMC-2-2',
        "description_en": '5 defenders + DMC screen. Against 4-1-3W-1-1 formations.',
        "description_it": '5 difensori + DMC schermo. Contro 4-1-3W-1-1.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'DMC', 'AML', 'AMR', 'ST', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['5 defenders', 'DMC shield', 'Two strikers', 'Counter ready'],
        "strengths_it": ['5 difensori', 'Scudo DMC', 'Due attaccanti', 'Pronto al contropiede'],
        "weaknesses_en": ['Very defensive', 'Limited midfield', 'AML/AMR isolated'],
        "weaknesses_it": ['Molto difensiva', 'Centrocampo limitato', 'AML/AMR isolati'],
        "tactic_type_en": 'Ultra Defensive / Counter',
        "tactic_type_it": 'Ultra Difensivo / Contropiede',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": '6 defenders! Long balls to striker duo on rare counters.',
                "tip_it": "6 difensori! Palle lunghe alla coppia d'attacco nei rari contropiedi."
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Stay deep. Use AML/AMR on counters to find strikers.',
                "tip_it": 'Resta profondo. Usa AML/AMR in contropiede per trovare gli attaccanti.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Push AML/AMR high. Create for the striker duo.',
                "tip_it": "Spingi AML/AMR in alto. Crea per la coppia d'attacco."
            }
        }
    },
    {
        "id": '5212x',
        "name": '5-2-1-2 X (X-Style)',
        "description_en": 'X-Style with DML/DMR. Against 5-2-1-2 formations.',
        "description_it": 'X-Style con DML/DMR. Contro 5-2-1-2.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'DML', 'DMR', 'AMC', 'ST', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['5 defenders', 'DML/DMR coverage', 'Counter ready', 'Hard to break'],
        "strengths_it": ['5 difensori', 'Copertura DML/DMR', 'Pronto al contropiede', 'Difficile da sfondare'],
        "weaknesses_en": ['Very defensive', 'Limited creativity', 'Needs fit DML/DMR'],
        "weaknesses_it": ['Molto difensiva', 'Creatività limitata', 'Richiede DML/DMR in forma'],
        "tactic_type_en": 'Ultra Defensive / X-Style',
        "tactic_type_it": 'Ultra Difensivo / X-Style',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Hard',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Full catenaccio! DML/DMR block midfield. Long to strikers.',
                "tip_it": 'Catenaccio totale! DML/DMR bloccano il centrocampo. Lungo agli attaccanti.'
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Stay organized. AMC links to strikers on counters.',
                "tip_it": 'Resta organizzato. AMC collega agli attaccanti in contropiede.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Push DML/DMR up. AMC orchestrates attacks to strikers.',
                "tip_it": 'Spingi DML/DMR in alto. AMC orchestra attacchi verso gli attaccanti.'
            }
        }
    },
    {
        "id": '522amlamr1',
        "name": '5-2-2(AML-AMR)-1',
        "description_en": '5 defenders with high wings. Against 4-2N-1-2W-1 formations.',
        "description_it": '5 difensori con ali alte. Contro 4-2N-1-2W-1.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['5 defenders', 'High AML/AMR', 'Counter ready', 'Solid base'],
        "strengths_it": ['5 difensori', 'AML/AMR alti', 'Pronto al contropiede', 'Base solida'],
        "weaknesses_en": ['Lone striker', 'Limited creativity', 'AML/AMR must track back'],
        "weaknesses_it": ['Attaccante solitario', 'Creatività limitata', 'AML/AMR devono rientrare'],
        "tactic_type_en": 'Defensive / Wide Counter',
        "tactic_type_it": 'Difensivo / Contropiede Largo',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": '5 at back tight. Long balls to AML/AMR then to ST.',
                "tip_it": '5 in difesa stretti. Palle lunghe ad AML/AMR poi a ST.'
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Stay compact. Use AML/AMR pace on counters.',
                "tip_it": 'Resta compatto. Usa la velocità di AML/AMR in contropiede.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Push AML/AMR very high. Create for lone striker.',
                "tip_it": "Spingi AML/AMR molto in alto. Crea per l'attaccante solitario."
            }
        }
    },
    {
        "id": '4131w1',
        "name": '4-1-3-1W-1',
        "description_en": 'Skewed winger formation. AMR (or AML) on same side as ST. Against 3-4-1-2 (defensive weakness).',
        "description_it": 'Ala skewata stesso lato del ST. Contro 3-4-1-2 (debolezza difensiva).',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'DMC', 'MC', 'MC', 'MC', 'AMR', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Skewed attack', 'Overload one side', 'Creative midfield', 'Exploits weak flanks'],
        "strengths_it": ['Attacco skewato', 'Sovraccarica un lato', 'Centrocampo creativo', 'Sfrutta fianchi deboli'],
        "weaknesses_en": ['Unbalanced', 'Needs quality AMR', 'Exposed on opposite flank'],
        "weaknesses_it": ['Sbilanciata', 'Richiede AMR di qualità', 'Esposta sul fianco opposto'],
        "tactic_type_en": 'Attacking / Skewed',
        "tactic_type_it": 'Attaccante / Skewata',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Right Flank',
            "passing_style": 'Mixed',
            "counter_attack": False,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Right Flank',
                "focus_passing_it": 'Fascia destra',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Counter through skewed side. AMR + ST combo on breaks.',
                "tip_it": 'Contropiede dal lato skewato. Combo AMR + ST nelle ripartenze.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Right Flank',
                "focus_passing_it": 'Fascia destra',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Overload right side. AMR and ST create overload.',
                "tip_it": 'Sovraccarica il lato destro. AMR e ST creano superiorità.'
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Right Flank',
                "focus_passing_it": 'Fascia destra',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'All-out attack on right side! 2nd half switch to high pressing.',
                "tip_it": 'Attacco totale sul lato destro! Nel 2°T passa a pressing alto.'
            }
        }
    },
    {
        "id": '3n52v',
        "name": '3N-5-2 V',
        "description_en": '3 DCs + 5 midfielders with high AML/AMR. Effective against parked bus formations.',
        "description_it": '3 DC + 5 MF con ali alte. Efficace contro bus parcheggiato.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['High wingers', 'Midfield control', 'Two strikers', 'Breaks parked bus'],
        "strengths_it": ['Ali alte', 'Controllo centrocampo', 'Due attaccanti', 'Sfonda il catenaccio'],
        "weaknesses_en": ['3 CBs exposed', 'No full-backs', 'High stamina needed'],
        "weaknesses_it": ['3 DC esposti', 'Nessun terzino', 'Richiede alta resistenza'],
        "tactic_type_en": 'Attacking / Anti-Parked Bus',
        "tactic_type_it": 'Attaccante / Anti-Catenaccio',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Protect 3 CBs. Use AML/AMR pace on counters to strikers.',
                "tip_it": 'Proteggi i 3 DC. Usa la velocità di AML/AMR in contropiede verso gli attaccanti.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Use width to stretch parked buses. AML/AMR + 2 STs overload.',
                "tip_it": "Usa l'ampiezza per allargare il catenaccio. AML/AMR + 2 ST sovraccaricano."
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'All-out attack! 7 players forward will destroy them!',
                "tip_it": 'Attacco totale! 7 giocatori in avanti li distruggeranno!'
            }
        }
    },
    {
        "id": '43n2w1',
        "name": '4-3N-2W-1',
        "description_en": '3 central MCs + high AML/AMR. Very common at high levels.',
        "description_it": '3 MC + AML/AMR alti. Molto diffusa ai livelli alti.',
        "positions": ['GK', 'DR', 'DC', 'DC', 'DL', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Central control', 'High wingers', 'Popular at high levels', 'Flexible'],
        "strengths_it": ['Controllo centrale', 'Ali alte', 'Popolare ai livelli alti', 'Flessibile'],
        "weaknesses_en": ['Lone striker', 'Needs quality MCs', 'Can be exposed on counters'],
        "weaknesses_it": ['Attaccante solitario', 'Richiede MC di qualità', 'Può essere esposta ai contropiedi'],
        "tactic_type_en": 'Attacking / High Level Meta',
        "tactic_type_it": 'Attaccante / Meta Alto Livello',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": False,
            "pressing": 'Normal',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Medium',
                "pressing_it": 'Medio',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": '3 MCs control center. AML/AMR break on counters to ST.',
                "tip_it": '3 MC controllano il centro. AML/AMR sfondano in contropiede verso ST.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Dominate midfield with 3 MCs. AML/AMR create for lone ST.',
                "tip_it": 'Domina il centrocampo con 3 MC. AML/AMR creano per ST solitario.'
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'All-out attack! Push all 6 attackers forward!',
                "tip_it": 'Attacco totale! Spingi tutti i 6 attaccanti in avanti!'
            }
        }
    },
    {
        "id": '3151amc',
        "name": '3-1-5-1 AMC',
        "description_en": 'Highly tactical formation with DMC shield and 5-man midfield including AMC as playmaker. 3 variants: A (Central Dominance), B (Balanced Control), C (Quick Transition). Very effective with a quality AMC.',
        "description_it": 'Formazione altamente tattica con DMC scudo e centrocampo a 5 con AMC come regista. 3 varianti: A (Dominio Centrale), B (Bilanciata-Controllo), C (Transizione Rapida). Molto efficace con un AMC di qualità.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'DMC', 'MR', 'MC', 'MC', 'ML', 'AMC', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['5-man midfield dominance', 'AMC as creative hub', '3 tactical variants', 'Flexible against any formation'],
        "strengths_it": ['Dominio centrocampo a 5', 'AMC come perno creativo', '3 varianti tattiche', 'Flessibile contro ogni formazione'],
        "weaknesses_en": ['Requires quality AMC (135+)', 'Only 3 defenders', 'Wings can be exposed'],
        "weaknesses_it": ['Richiede AMC di qualità (135+)', 'Solo 3 difensori', 'Fasce possono essere esposte'],
        "tactic_type_en": 'META 2025 / Multi-Variant',
        "tactic_type_it": 'META 2025 / Multi-Variante',
        "arrows": '★ Variante A: MC↑ | Variante C: MR↓ ML↓',
        "variants": {
            "A": {
                "name_en": 'Central Dominance',
                "name_it": 'Dominio Centrale',
                "mentality": 'Attacking',
                "mentality_it": 'Offensiva',
                "passing_focus": 'Through the Middle',
                "passing_focus_it": 'Per il Centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "pressing": 'High',
                "pressing_it": 'Alto',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "counter_attack": False,
                "arrows": {
                    "MC": '↑'
                },
                "best_against": ['4-4-2', '4-1-4-1', '4-3-1-2', '3-5-2'],
                "tip_en": 'Ideal with top AMC (135+). Crush weaker opponents. AMC is the creative hub.',
                "tip_it": 'Ideale con AMC top (135+). Schiaccia avversari più deboli. AMC è il perno creativo.'
            },
            "B": {
                "name_en": 'Balanced Control',
                "name_it": 'Bilanciata-Controllo',
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "passing_focus": 'Mixed',
                "passing_focus_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "counter_attack": True,
                "arrows": {

                },
                "best_against": ['3-4-3', '4-2-3-1', '4-5-1'],
                "tip_en": 'For balanced matches. Safer at the back, AMC and ST have freedom.',
                "tip_it": 'Per partite equilibrate. Più sicura dietro, AMC e ST con libertà.'
            },
            "C": {
                "name_en": 'Quick Transition',
                "name_it": 'Transizione Rapida',
                "mentality": 'Defensive',
                "mentality_it": 'Difensiva',
                "passing_focus": 'Mixed',
                "passing_focus_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lunghi',
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "counter_attack": True,
                "arrows": {
                    "MR": '↓',
                    "ML": '↓'
                },
                "best_against": ['4-3-3', '5-3-2', '4-2-2-2'],
                "tip_en": 'Perfect vs high-possession teams. Use AMC-ST-MR-ML speed on counters.',
                "tip_it": 'Perfetta vs squadre con alto possesso. Usa velocità AMC-ST-MR-ML nei contropiedi.'
            }
        },
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Short',
            "counter_attack": False,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Man-to-Man',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensiva',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lunghi',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "variant": 'C',
                "tip_en": 'Use Variant C (Quick Transition). Stay compact, counter with AMC-ST speed. MR/ML with backward arrows.',
                "tip_it": 'Usa Variante C (Transizione Rapida). Resta compatto, contropiede con velocità AMC-ST. MR/ML con frecce indietro.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "variant": 'B',
                "tip_en": 'Use Variant B (Balanced). Safer at the back, AMC and ST have freedom to create.',
                "tip_it": 'Usa Variante B (Bilanciata). Più sicura dietro, AMC e ST con libertà di creare.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Offensiva',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il Centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "variant": 'A',
                "tip_en": 'Use Variant A (Central Dominance). Crush them! High press, AMC as creative hub, MC forward arrows.',
                "tip_it": 'Usa Variante A (Dominio Centrale). Schiaccialo! Pressing alto, AMC come perno, MC con frecce avanti.'
            }
        }
    },
    {
        "id": '31411',
        "name": '3-1-4-1-1',
        "description_en": 'The most popular META formation in 2026. 3 DCs with DMC shield, 4 midfielders, AMC as second striker. DMC arrow down, AMC arrow up for maximum effectiveness.',
        "description_it": 'La formazione META più popolare nel 2026. 3 DC con scudo DMC, 4 centrocampisti, AMC come secondo attaccante. Freccia DMC giù, freccia AMC su per massima efficacia.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Solid 3-man defense + DMC shield', 'AMC acts as second striker', 'Wide coverage with ML/MR', 'Great counter-attacking', 'Beats 12%+ stronger opponents'],
        "strengths_it": ['Difesa solida a 3 + scudo DMC', 'AMC agisce da secondo attaccante', 'Copertura ampia con ML/MR', 'Ottimo contropiede', 'Batte avversari 12%+ più forti'],
        "weaknesses_en": ['Vulnerable to 3-striker formations', 'Wings can be exposed', 'Requires quality DMC'],
        "weaknesses_it": ['Vulnerabile a formazioni con 3 attaccanti', 'Fasce possono essere esposte', 'Richiede DMC di qualità'],
        "tactic_type_en": '★ META 2026 / Counter-Attack',
        "tactic_type_it": '★ META 2026 / Contropiede',
        "arrows": 'DMC↓ AMC↑',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Easy',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Sulle Fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "tip_en": "Stay compact! DMC↓ to protect DCs. Counter through flanks. Don't chase the ball, let them come.",
                "tip_it": 'Resta compatto! DMC↓ per proteggere i DC. Contropiede sulle fasce. Non rincorrere, lascia che vengano.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "tip_en": 'Balance attack and defense. AMC↑ for extra goal threat. Use ML/MR for width.',
                "tip_it": 'Equilibra attacco e difesa. AMC↑ per minaccia extra. Usa ML/MR per ampiezza.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Offensiva',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il Centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Dominate! Push everyone forward. AMC↑ MC↑ for 3-man attack. High press to suffocate.',
                "tip_it": 'Domina! Spingi tutti avanti. AMC↑ MC↑ per attacco a 3. Pressing alto per soffocare.'
            }
        }
    },
    {
        "id": '41221',
        "name": '4-1-2-2-1',
        "description_en": 'Super defensive formation with 5 virtual defenders. DL-DC-DC-DR-DMC creates a wall. 2 MC + 2 wingers for balance. Great for parking the bus.',
        "description_it": 'Formazione super difensiva con 5 difensori virtuali. DL-DC-DC-DR-DMC crea un muro. 2 MC + 2 ali per equilibrio. Ottima per parcheggiare il bus.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        "category_en": 'Ultra Defensive',
        "category_it": 'Ultra Difensiva',
        "strengths_en": ['5-man virtual defense', 'Almost impossible to break', 'Hard tackling effective', 'Zonal marking dominant', 'Best for weaker teams'],
        "strengths_it": ['Difesa virtuale a 5', 'Quasi impossibile da sfondare', 'Contrasti duri efficaci', 'Marcatura a zona dominante', 'Migliore per squadre deboli'],
        "weaknesses_en": ['Very limited attack', 'Relies on counters only', 'Can be boring to play'],
        "weaknesses_it": ['Attacco molto limitato', 'Si basa solo sui contropiedi', 'Può essere noiosa da giocare'],
        "tactic_type_en": 'META 2026 / Ultra Defensive',
        "tactic_type_it": 'META 2026 / Ultra Difensiva',
        "arrows": 'DMC↓ MC↓',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Hard',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Ultra Difensiva',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Sulle Fasce',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "tip_en": 'PARK THE BUS! Everyone defends. Only AML/AMR and ST go forward on counters. Pray for 0-0.',
                "tip_it": 'PARCHEGGIA IL BUS! Tutti difendono. Solo AML/AMR e ST avanti in contropiede. Prega per lo 0-0.'
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensiva',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Sulle Fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "tip_en": 'Stay solid. Let them have the ball. Strike fast on counter with AML/AMR pace.',
                "tip_it": 'Resta solido. Lascia che abbiano palla. Colpisci veloce in contropiede con velocità AML/AMR.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": True,
                "tip_en": 'Push MC forward slightly. Still counter-focused but more possession.',
                "tip_it": 'Spingi MC leggermente avanti. Ancora focus contropiede ma più possesso.'
            }
        }
    },
    {
        "id": 'fn9w',
        "name": 'False Nine + Wingers',
        "description_en": 'NEW META attacking system. AMC plays as False Nine dropping deep, ML/MR push to AML/AMR as inverted wingers. Only 3 attackers but devastating effectiveness.',
        "description_it": 'NUOVO sistema META offensivo. AMC gioca come Falso Nove arretrando, ML/MR spingono a AML/AMR come ali invertite. Solo 3 attaccanti ma efficacia devastante.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'AMR', 'AMC'],
        "category_en": 'Attacking',
        "category_it": 'Offensiva',
        "strengths_en": ['False Nine pulls defenders out', 'Wingers exploit space', 'Can switch formation live', 'No subs needed to attack', 'Confuses opponent'],
        "strengths_it": ['Falso Nove attira difensori', 'Ali sfruttano spazi', 'Può cambiare formazione live', 'Non servono sostituzioni per attaccare', "Confonde l'avversario"],
        "weaknesses_en": ['Requires very specific players', 'No true striker', 'Complex to master'],
        "weaknesses_it": ['Richiede giocatori molto specifici', 'Nessun vero attaccante', 'Complessa da padroneggiare'],
        "tactic_type_en": '★ NEW META 2026 / False Nine',
        "tactic_type_it": '★ NUOVO META 2026 / Falso Nove',
        "arrows": 'AMC↓ (as False Nine) AML↑ AMR↑',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Short',
            "counter_attack": False,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Normal',
                "pressing_it": 'Normale',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": False,
                "tip_en": "False Nine drops, AML/AMR run into space. Quick 1-2s in the middle. Don't force it.",
                "tip_it": 'Falso Nove arretra, AML/AMR corrono negli spazi. Rapidi 1-2 al centro. Non forzare.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Offensiva',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il Centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'A Zona',
                "offside_trap": False,
                "tip_en": 'Full False Nine system. AMC drops, AML/AMR attack. Confuse their defense!',
                "tip_it": 'Sistema Falso Nove completo. AMC arretra, AML/AMR attaccano. Confondi la loro difesa!'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Offensiva',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il Centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Push False Nine to ST, wingers to AML/AMR. Full attack mode! 3 attackers vs their weak defense.',
                "tip_it": 'Spingi Falso Nove a ST, ali a AML/AMR. Modalità attacco totale! 3 attaccanti vs loro difesa debole.'
            }
        }
    },
    {
        "id": '424',
        "name": '4-2-4',
        "description_en": '4-2-4 - Attacking formation. Maximum aggression; four fixed attackers.',
        "description_it": '4-2-4 - formazione attaccante. Massima aggressività; 4 attaccanti fissi.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'AML', 'ST', 'ST', 'AMR'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Maximum aggression', 'Four fixed attackers', 'High goal output'],
        "strengths_it": ['Massima aggressività', '4 attaccanti fissi', 'Alta produzione di gol'],
        "weaknesses_en": ['No real midfield', 'Very exposed defense'],
        "weaknesses_it": ['Centrocampo assente', 'Difesa molto esposta'],
        "tactic_type_en": 'All-Out Attack',
        "tactic_type_it": 'Attacco Totale',
        "recommended_tactics": {
            "mentality": 'Hard Attacking',
            "focus_passing": 'Mixed',
            "passing_style": 'Long',
            "counter_attack": False,
            "pressing": 'High',
            "tackling": 'Hard',
            "marking": 'Man-to-Man',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 4-2-4, drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 4-2-4, abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Ultra-attacking shape for desperate comebacks, but leaves the defense completely open.',
                "tip_it": 'Modulo ultra-offensivo per rimonte disperate, ma lascia la difesa totalmente scoperta.'
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 4-2-4, raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 4-2-4, alza pressing e marcatura a uomo per dominare.'
            }
        }
    },
    {
        "id": '41311',
        "name": '4-1-3-1-1',
        "description_en": '4-1-3-1-1 - Balanced formation. Defensive solidity; frequent clean sheets.',
        "description_it": '4-1-3-1-1 - formazione bilanciata. Solidità difensiva; clean sheet frequenti.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Defensive solidity', 'Frequent clean sheets', 'Neutralizes the 4-3-3'],
        "strengths_it": ['Solidità difensiva', 'Clean sheet frequenti', 'Neutralizza il 4-3-3'],
        "weaknesses_en": ['Narrow-margin wins', 'Limited attack'],
        "weaknesses_it": ['Vittorie di misura', 'Attacco limitato'],
        "tactic_type_en": 'Balanced / Clean Sheet',
        "tactic_type_it": 'Bilanciato / Porta Inviolata',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Mixed',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": True
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 4-1-3-1-1, drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 4-1-3-1-1, abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": "Excellent for protecting the result and shutting down the opponent's wide attacks.",
                "tip_it": 'Eccellente per proteggere il risultato e annullare gli attacchi esterni avversari.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 4-1-3-1-1, raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 4-1-3-1-1, alza pressing e marcatura a uomo per dominare.'
            }
        }
    },
    {
        "id": '4321xt',
        "name": '4-3-2-1 XT (Xmas Tree)',
        "description_en": '4-3-2-1 XT (Xmas Tree) - Defensive formation. Powerful midfield; flank protection.',
        "description_it": '4-3-2-1 XT (Xmas Tree) - formazione difensiva. Centrocampo potente; protezione dei fianchi.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['Powerful midfield', 'Flank protection', 'Midfield density'],
        "strengths_it": ['Centrocampo potente', 'Protezione dei fianchi', 'Densità mediana'],
        "weaknesses_en": ['Isolated strikers', 'Lacks width'],
        "weaknesses_it": ['Punte isolate', 'Manca di ampiezza'],
        "tactic_type_en": 'Defensive / Midfield Control',
        "tactic_type_it": 'Difensivo / Controllo Centrocampo',
        "recommended_tactics": {
            "mentality": 'Defensive',
            "focus_passing": 'Down Both Flanks',
            "passing_style": 'Mixed',
            "counter_attack": False,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 4-3-2-1 XT (Xmas Tree), drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 4-3-2-1 XT (Xmas Tree), abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Ideal to exploit the flanks and keep a solid midfield against versatile formations.',
                "tip_it": 'Ideale per sfruttare le fasce e mantenere un centrocampo solido contro formazioni versatili.'
            },
            "weak": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Down Both Flanks',
                "focus_passing_it": 'Per entrambe le fasce',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 4-3-2-1 XT (Xmas Tree), raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 4-3-2-1 XT (Xmas Tree), alza pressing e marcatura a uomo per dominare.'
            }
        }
    },
    {
        "id": '532',
        "name": '5-3-2',
        "description_en": '5-3-2 - Defensive formation. Prevents goals; central density.',
        "description_it": '5-3-2 - formazione difensiva. Previene i gol; densità centrale.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'ST', 'ST'],
        "category_en": 'Defensive',
        "category_it": 'Difensiva',
        "strengths_en": ['Prevents goals', 'Central density', 'Defensive stability'],
        "strengths_it": ['Previene i gol', 'Densità centrale', 'Stabilità difensiva'],
        "weaknesses_en": ['Few scoring chances', 'Low defensive line'],
        "weaknesses_it": ['Poche occasioni da gol', 'Baricentro basso'],
        "tactic_type_en": 'Ultra Defensive / Bus Parking',
        "tactic_type_it": 'Ultra Difensivo / Catenaccio',
        "recommended_tactics": {
            "mentality": 'Hard Defending',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Long',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 5-3-2, drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 5-3-2, abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Hard Defending',
                "mentality_it": 'Molto Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": "The best choice to 'park the bus' and defend a lead you've earned.",
                "tip_it": "La scelta migliore per 'parcheggiare l'autobus' e difendere un vantaggio acquisito."
            },
            "weak": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Long',
                "passing_style_it": 'Lungo',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 5-3-2, raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 5-3-2, alza pressing e marcatura a uomo per dominare.'
            }
        }
    },
    {
        "id": '413n2',
        "name": '4-1-3N-2',
        "description_en": '4-1-3N-2 - Balanced formation. Beats the 4-2-3-1; balance between the lines.',
        "description_it": '4-1-3N-2 - formazione bilanciata. Batte il 4-2-3-1; equilibrio tra le linee.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'MC', 'ST', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Beats the 4-2-3-1', 'Balance between the lines', 'Central density'],
        "strengths_it": ['Batte il 4-2-3-1', 'Equilibrio tra le linee', 'Densità centrale'],
        "weaknesses_en": ['Struggles against wide play', 'Requires quality MCs'],
        "weaknesses_it": ['Soffre il gioco laterale', 'Richiede MC di qualità'],
        "tactic_type_en": 'Balanced / Central Counter',
        "tactic_type_it": 'Bilanciato / Contropiede Centrale',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Mixed',
            "counter_attack": True,
            "pressing": 'Low',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 4-1-3N-2, drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 4-1-3N-2, abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Great for dominating central possession and striking on the counter through the middle.',
                "tip_it": 'Ottima per dominare il possesso centrale e colpire in contropiede attraverso il centro.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 4-1-3N-2, raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 4-1-3N-2, alza pressing e marcatura a uomo per dominare.'
            }
        }
    },
    {
        "id": '3412',
        "name": '3-4-1-2',
        "description_en": '3-4-1-2 - Attacking formation. Central presence; dominates the final third.',
        "description_it": '3-4-1-2 - formazione attaccante. Presenza centrale; domina la trequarti.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Central presence', 'Dominates the final third', 'Numerical superiority'],
        "strengths_it": ['Presenza centrale', 'Domina la trequarti', 'Superiorità numerica'],
        "weaknesses_en": ['Weak wide defense', 'Vulnerable on the flanks'],
        "weaknesses_it": ['Difesa laterale debole', 'Vulnerabile sulle fasce'],
        "tactic_type_en": 'Attacking / Central',
        "tactic_type_it": 'Attaccante / Centrale',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Mixed',
            "counter_attack": False,
            "pressing": 'Medium',
            "tackling": 'Normal',
            "marking": 'Man-to-Man',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 3-4-1-2, drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 3-4-1-2, abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Effective at breaking through centrally, but needs disciplined full-backs to cover the wide spaces.',
                "tip_it": 'Efficace per sfondare centralmente, ma richiede terzini bloccati per coprire le praterie esterne.'
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Mixed',
                "passing_style_it": 'Misto',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 3-4-1-2, raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 3-4-1-2, alza pressing e marcatura a uomo per dominare.'
            }
        }
    },
    {
        "id": '31312',
        "name": '3-1-3-1-2',
        "description_en": '3-1-3-1-2 - Attacking formation. Many shooting chances; attacking orientation.',
        "description_it": '3-1-3-1-2 - formazione attaccante. Molte opportunità di tiro; orientamento offensivo.',
        "positions": ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        "category_en": 'Attacking',
        "category_it": 'Attaccante',
        "strengths_en": ['Many shooting chances', 'Attacking orientation', 'Flexibility'],
        "strengths_it": ['Molte opportunità di tiro', 'Orientamento offensivo', 'Flessibilità'],
        "weaknesses_en": ['Exposed to counters', 'Risky back three'],
        "weaknesses_it": ['Esposta ai contropiedi', 'Difesa a tre rischiosa'],
        "tactic_type_en": 'Attacking / High Press',
        "tactic_type_it": 'Attaccante / Pressing Alto',
        "recommended_tactics": {
            "mentality": 'Attacking',
            "focus_passing": 'Through the Middle',
            "passing_style": 'Short',
            "counter_attack": False,
            "pressing": 'High',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 3-1-3-1-2, drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 3-1-3-1-2, abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'A basic attacking shape to create constant scoring chances against static defenses.',
                "tip_it": "Modulo d'attacco basilare per creare costanti occasioni da gol contro difese statiche."
            },
            "weak": {
                "mentality": 'Hard Attacking',
                "mentality_it": 'Molto Attaccante',
                "focus_passing": 'Through the Middle',
                "focus_passing_it": 'Per il centro',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 3-1-3-1-2, raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 3-1-3-1-2, alza pressing e marcatura a uomo per dominare.'
            }
        }
    },
    {
        "id": '43n3',
        "name": '4-3N-3',
        "description_en": '4-3N-3 - Balanced formation. Counters the 4-5-1 V-Style; attacking density.',
        "description_it": '4-3N-3 - formazione bilanciata. Counter del 4-5-1 V-Style; densità offensiva.',
        "positions": ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'ST', 'ST', 'ST'],
        "category_en": 'Balanced',
        "category_it": 'Bilanciata',
        "strengths_en": ['Counters the 4-5-1 V-Style', 'Attacking density', 'Central pressing'],
        "strengths_it": ['Counter del 4-5-1 V-Style', 'Densità offensiva', 'Pressing centrale'],
        "weaknesses_en": ['Lacks width', 'Vulnerable if they stretch the play'],
        "weaknesses_it": ['Manca di ampiezza', 'Vulnerabile se allargano il gioco'],
        "tactic_type_en": 'Balanced / Anti V-Style',
        "tactic_type_it": 'Bilanciato / Anti V-Style',
        "recommended_tactics": {
            "mentality": 'Normal',
            "focus_passing": 'Mixed',
            "passing_style": 'Short',
            "counter_attack": False,
            "pressing": 'Medium',
            "tackling": 'Normal',
            "marking": 'Zonal',
            "offside_trap": False
        },
        "opponent_settings": {
            "strong": {
                "mentality": 'Defensive',
                "mentality_it": 'Difensivo',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Easy',
                "tackling_it": 'Facile',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": True,
                "tip_en": 'Against stronger sides, stay compact in the 4-3N-3, drop the pressing and hit on the counter.',
                "tip_it": 'Contro avversari più forti, resta compatto col 4-3N-3, abbassa il pressing e riparti in contropiede.'
            },
            "equal": {
                "mentality": 'Normal',
                "mentality_it": 'Normale',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": True,
                "pressing": 'Low',
                "pressing_it": 'Basso',
                "tackling": 'Normal',
                "tackling_it": 'Normale',
                "marking": 'Zonal',
                "marking_it": 'Zonale',
                "offside_trap": False,
                "tip_en": 'Aggressive variant ideal to unlock crowded midfields and dominate the central zone.',
                "tip_it": 'Variante aggressiva ideale per scardinare centrocampi folti e dominare la zona centrale.'
            },
            "weak": {
                "mentality": 'Attacking',
                "mentality_it": 'Attaccante',
                "focus_passing": 'Mixed',
                "focus_passing_it": 'Misto',
                "passing_style": 'Short',
                "passing_style_it": 'Corti',
                "counter_attack": False,
                "pressing": 'High',
                "pressing_it": 'Alto',
                "tackling": 'Hard',
                "tackling_it": 'Duro',
                "marking": 'Man-to-Man',
                "marking_it": 'Uomo a Uomo',
                "offside_trap": False,
                "tip_en": 'Against weaker sides, push high with the 4-3N-3, raise pressing and man-marking to dominate.',
                "tip_it": 'Contro avversari più deboli, spingi alto col 4-3N-3, alza pressing e marcatura a uomo per dominare.'
            }
        }
    }
]

# ==================== COUNTER ENGINE v6 — FRECCE COMPLETE + META 2025 ====================
# Per ogni scenario: TUTTE le posizioni del modulo consigliato
# ctrl: SI/NO | press: Alto/Basso | fuo: SI/NO
# Frecce: ogni entry copre TUTTI i ruoli del modulo consigliato

COUNTER_ENGINE = [
    # ═══════════════════════════════
    # ⚡ VS ATTACCANTI (3 difensori)
    # ═══════════════════════════════
    {
        "av": "3N-5-2 F",
        "cat": "att",
        "forte": {
            "mod": "4-2-3-1",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Misto",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "MC": "↓", "AML": "↑", "AMC": "↑", "AMR": "↑", "ST": "—"},
            "w": "5 MF avversari al centro: 2 MC tuoi coprono. AML/AMR pronti al contropiede sulle fasce libere"
        },
        "pari": {
            "mod": "4-3N-2W-1",
            "alt": "4-2-3-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Sfrutta terzini scoperti avversari. Non aprire il centro"
        },
        "debole": {
            "mod": "3-1-4-2",
            "alt": "3-5-2 F",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↓", "ML": "↑", "MC": "—", "MR": "↑", "ST": "—"},
            "w": "Nessun terzino avversario: aggredisci con 4 MC sulle fasce spalancate"
        }
    },
    {
        "av": "3W-5-2 F",
        "cat": "att",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-2-3-1",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Ali larghe: DMC+2MC coprono il centro. AML/AMR in contropiede"
        },
        "pari": {
            "mod": "4-5-1 V",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Mantieni compattezza. Le ali W spingono alto e lasciano spazio dietro"
        },
        "debole": {
            "mod": "3-1-3N-2W-1",
            "alt": "3-5-2 V",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↓", "MC": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "3 DC senza terzini avversari: spazio laterale enorme. Sfruttalo con le ali"
        }
    },
    {
        "av": "3N-4-3",
        "cat": "att",
        "forte": {
            "mod": "5-4-1 F",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Misto",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Easy",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "5 difensori bloccano 3 attaccanti. Non uscire mai dalla posizione. Contropiede veloce"
        },
        "pari": {
            "mod": "4-4-2 C",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "SI",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "ML": "—", "MC": "—", "MR": "—", "ST": "↑"},
            "w": "4-3-3 pericoloso sulle fasce. ST con freccia avanti per occupare i 3 DC"
        },
        "debole": {
            "mod": "3-5-2 F",
            "alt": "4-2-2-2 H",
            "men": "Offensiva",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Hard",
            "marc": "Uomo",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "5 MC domina il centro vs 3 MC avversari. Sfrutta mancanza DMC"
        }
    },
    {
        "av": "3W-4-3",
        "cat": "att",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "5-4-1 F",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Easy",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "3 attaccanti larghi: non avanzare mai i terzini. DMC fondamentale"
        },
        "pari": {
            "mod": "4-2-2-2 H",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Hexagon sfrutta le fasce scoperte del 3-4-3 che non ha terzini"
        },
        "debole": {
            "mod": "3-5-2 V",
            "alt": "3-5-2 F",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "5 MF vs 3 MC: dominio totale al centro poi sfonda in ampiezza"
        }
    },
    {
        "av": "3W-1-4-2",
        "cat": "att",
        "forte": {
            "mod": "4-1-2-1-2 ND",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AMC": "—", "ST": "—"},
            "w": "ND copre il centro denso. Evita di avanzare i terzini"
        },
        "pari": {
            "mod": "4-1-2-1-2 ND",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Centro",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "SI",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "DMC": "↓", "MC": "—", "AMC": "↑", "ST": "—"},
            "w": "Mantieni diamond compatto. AMC sfrutta lo spazio dietro i loro MC"
        },
        "debole": {
            "mod": "3-4-1-2",
            "alt": "3-5-2 F",
            "men": "Offensiva",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "AMC": "↑", "ST": "—"},
            "w": "Aggredisci le fasce difensive aperte del 3-1-4-2 senza terzini"
        }
    },
    {
        "av": "3N-1-4-2",
        "cat": "att",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-2-3-1",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "4 MC avversari al centro: DMC è lo scudo. Sfrutta le fasce in contropiede"
        },
        "pari": {
            "mod": "4-5-1 V",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Avversario senza terzini: sfrutta le fasce con AML/AMR alti"
        },
        "debole": {
            "mod": "3-5-1-1 V",
            "alt": "4-3N-2W-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "5 MF vs loro 4+1: schiacciante. Aggredisci le fasce aperte"
        }
    },
    {
        "av": "3N-5-2 V",
        "cat": "att",
        "forte": {
            "mod": "3-2-2-2-1 B",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Misto",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DC": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Butterfly: 2 DMC schermo vs loro centro affollato. AML/AMR in contropiede"
        },
        "pari": {
            "mod": "4-3N-2W-1",
            "alt": "4-2-2-2 H",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Sfrutta le fasce libere: il 3-5-2 V non ha terzini"
        },
        "debole": {
            "mod": "3-1-3N-3",
            "alt": "3-5-2 V",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Hard",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "MC": "↑", "ST": "—"},
            "w": "Sovraffolla il centrocampo poi sfonda in ampiezza. DMC con freccia avanti"
        }
    },
    {
        "av": "3N-1-3W-1-2 D (Dandelion)",
        "cat": "att",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-2-3-1",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Dandelion: 3N+3W affolla tutto. Sfrutta le fasce libere in contropiede"
        },
        "pari": {
            "mod": "4-4-2 C",
            "alt": "4-1-2-1-2 WD",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "Il 4-4-2 bilancia bene sia centro che fasce contro il Dandelion"
        },
        "debole": {
            "mod": "3-5-1-1 V",
            "alt": "4-4-2 C",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "5 MF domina il loro 3+3+1: nessuno può seguire tutti i tuoi giocatori"
        }
    },
    {
        "av": "3N-2-2-2-1 B (Butterfly)",
        "cat": "att",
        "forte": {
            "mod": "3N-5-2 F",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Misto",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DC": "↓", "ML": "↑", "MC": "—", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Butterfly 3DC: 2 DMC + 2 MC + 2 AML/AMR. Molto bilanciato. Sii paziente"
        },
        "pari": {
            "mod": "4-3N-2W-1",
            "alt": "4-2-2-2 H",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Sfrutta fasce libere. Il Butterfly non ha terzini"
        },
        "debole": {
            "mod": "3N-5-2 F",
            "alt": "3-5-2 V",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Hard",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "5 MF attaccante vs loro 2 DMC: dominio assoluto"
        }
    },
    {
        "av": "3W-2(DMC)-3W-1-1 ML (Maple Leaf)",
        "cat": "att",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-2-3-1",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Maple Leaf: 3 ali Larghe + AMC. DMC tuo marca l'AMC avversario"
        },
        "pari": {
            "mod": "3N-1-4-2",
            "alt": "4-5-1 V",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "DMC": "↓", "ML": "↑", "MC": "—", "MR": "↑", "ST": "—"},
            "w": "4 MC vs loro 2 DMC: vantaggio numerico. Sfrutta le fasce"
        },
        "debole": {
            "mod": "3W-5-2 V",
            "alt": "3N-1-4-2",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Specchia le loro ali Wide con AML/AMR. Dominio assoluto"
        }
    },

    # ═══════════════════════════════
    # ⚖️ VS BILANCIATI (4 difensori)
    # ═══════════════════════════════
    {
        "av": "4-4-2 C",
        "cat": "neu",
        "forte": {
            "mod": "3-2-2-2-1 B",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Centro",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DC": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "4-4-2 forte in ampiezza: Butterfly copre tutto. Evita di allargare il gioco"
        },
        "pari": {
            "mod": "4-1-2-1-2 ND",
            "alt": "4-3N-2W-1",
            "men": "Offensiva",
            "pass": "Centro",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AMC": "↑", "ST": "↑"},
            "w": "ND attacca il centro debole del 4-4-2. AMC e ST con frecce avanti"
        },
        "debole": {
            "mod": "4-1-2-1-2 ND",
            "alt": "3-5-2 F",
            "men": "Hard Att.",
            "pass": "Centro",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Hard",
            "marc": "Uomo",
            "fuo": "SI",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "DMC": "—", "MC": "↑", "AMC": "↑", "ST": "↑"},
            "w": "Schiaccia il centro: il 4-4-2 non ha AMC. DMC neutro per trasformarsi in MC"
        }
    },
    {
        "av": "4-5-1 V",
        "cat": "neu",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-2-3-1",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Speculare: chi sbaglia primo perde. Sii paziente, aspetta l'errore avversario"
        },
        "pari": {
            "mod": "4-3N-3",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "MC": "—", "ST": "—"},
            "w": "3 attaccanti contro DMC+2MC: premi sulle fasce dove sono scoperti"
        },
        "debole": {
            "mod": "3-3-1-3",
            "alt": "3W-1-2-3W-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "MC": "↑", "AMC": "↑", "ST": "—"},
            "w": "3 attaccanti fanno saltare la loro linea difensiva a 4. AMC tra le linee"
        }
    },
    {
        "av": "4-5-1 F",
        "cat": "neu",
        "forte": {
            "mod": "4-1-4-1",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Misto",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Easy",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "5 MC piatti difensivi ma prevedibili. Contropiede veloce sulle fasce"
        },
        "pari": {
            "mod": "3-5-2 V",
            "alt": "3-5-2 F",
            "men": "Normale",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "3 DC + 5 MF: match-up paritario. Usa passaggi lunghi per sfuggire al pressing"
        },
        "debole": {
            "mod": "3-5-2 F",
            "alt": "4-3N-3",
            "men": "Offensiva",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "Premi alto: 4-5-1 F non ha attaccanti pronti al contropiede rapido"
        }
    },
    {
        "av": "4-1-2-1-2 ND",
        "cat": "neu",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "3-5-2 V",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "ND pericoloso al centro: AML/AMR sfruttano i fianchi totalmente vuoti"
        },
        "pari": {
            "mod": "3N-5-2 V",
            "alt": "4-5-1 V",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "ML": "—", "MC": "—", "MR": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Flanchi liberi del ND: attacca con AML e AMR che non hanno avversari"
        },
        "debole": {
            "mod": "3N-5-2 V",
            "alt": "4-2-2-2 H",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Hard",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Aggredisci: il ND non ha terzini né ali. Completamente aperto sui lati"
        }
    },
    {
        "av": "4-2-2-2 H",
        "cat": "neu",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "3-2-2-2-1 B",
            "men": "Difensiva",
            "pass": "Centro",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Hexagon con AML/AMR alti: DMC fondamentale schermo al centro"
        },
        "pari": {
            "mod": "3N-4-1-2",
            "alt": "4-5-1 V",
            "men": "Normale",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "DMC": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "4 MC vs loro 2 MC: sovraffolla il centro e bypassa le loro ali"
        },
        "debole": {
            "mod": "3N-4-3",
            "alt": "3-4-3",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "3 attaccanti vs loro 2 MC soli: troppo da gestire. Dominio assoluto"
        }
    },
    {
        "av": "4-3N-2W-1",
        "cat": "neu",
        "forte": {
            "mod": "4-4-1-1",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "3 MC + 2 AM: molto bilanciato. 4-4-1-1 copre bene sia centro che fasce"
        },
        "pari": {
            "mod": "3-1-4-1-1",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "DMC": "↓", "ML": "—", "MC": "—", "MR": "—", "AMC": "↑", "ST": "—"},
            "w": "★ META 2025: 3-1-4-1-1 sfrutta le fasce con ML/MR e trova AMC tra le linee"
        },
        "debole": {
            "mod": "3-1-4-1-1",
            "alt": "3-5-2 V",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "AMC": "↑", "ST": "—"},
            "w": "Domina con 4 MC + AMC. I loro 2W avanzati si ritrovano isolati"
        }
    },
    {
        "av": "4-1-4-1",
        "cat": "neu",
        "forte": {
            "mod": "4-2-3-1",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Easy",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "MC": "—", "AML": "↑", "AMC": "↑", "AMR": "↑", "ST": "—"},
            "w": "4-1-4-1 è solido: DMC+4MF controllano. Sfrutta le fasce in contropiede"
        },
        "pari": {
            "mod": "4-2-2-2 H",
            "alt": "3W-4-3",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Hexagon: AML/AMR sfruttano lo spazio tra ML/MR e terzini avversari"
        },
        "debole": {
            "mod": "3-5-2 V",
            "alt": "4-3N-3",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "Premi alto con 5 MF: sovrasta il loro centrocampo"
        }
    },
    {
        "av": "4-4-1-1",
        "cat": "neu",
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-2-3-1",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "L'AMC avversario è la minaccia principale: DMC lo neutralizza. AML/AMR liberi"
        },
        "pari": {
            "mod": "3-5-2 F",
            "alt": "4-5-1 V",
            "men": "Normale",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "5 MF vs 4 MF: vantaggio numerico al centro. Sfrutta le fasce"
        },
        "debole": {
            "mod": "3-5-2 F",
            "alt": "4-3N-3",
            "men": "Offensiva",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "Con netto vantaggio: 5 MC + 2 ST vs loro 4 MF. Aggredisci da subito"
        }
    },
    {
        "av": "4-2-3-1",
        "cat": "neu",
        "forte": {
            "mod": "5-4-1 F",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Easy",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "5 difensori bloccano l'AMC. Contropiede dalle fasce con ML/MR"
        },
        "pari": {
            "mod": "4-1-4-1",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "DMC": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "DMC copre il loro AMC. ML/MR sfruttano le fasce. Non avanzare i terzini"
        },
        "debole": {
            "mod": "3-1-4-2",
            "alt": "4-3N-3",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "—", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "4 MC contro loro 2: domina il centrocampo. DMC neutro"
        }
    },
    {
        "av": "3-4-1-2",
        "cat": "neu",
        "forte": {
            "mod": "4-1-2-1-2 ND",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AMC": "—", "ST": "—"},
            "w": "Debolezza del 3-4-1-2: le fasce difensive aperte. ND aspetta e contrattacca"
        },
        "pari": {
            "mod": "4-1-3W-1-1",
            "alt": "3-1-3W-1-2",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "DMC": "↓", "ML": "↑", "MC": "—", "MR": "↑", "AMC": "—", "ST": "—"},
            "w": "★ Ala skewata stesso lato del ST. Fasce scoperte del 3-4-1-2 = vulnerabilità"
        },
        "debole": {
            "mod": "3-5-2 F",
            "alt": "4-1-3W-1-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "5 MF + attacco sulle fasce aperte. Nessun terzino avversario = distruttivo"
        }
    },

    # ═══════════════════════════════════════════
    # 🔥 FORMAZIONI META 2025 (nuove!)
    # ═══════════════════════════════════════════
    {
        "av": "3N-1-4-1-1",
        "cat": "att",
        "meta": True,
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-1-2-1-2 ND",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "★ META: 3-1-4-1-1 molto pericoloso. DMC marca il loro AMC. Sfrutta le fasce vuote"
        },
        "pari": {
            "mod": "4-1-2-1-2 ND",
            "alt": "4-5-1 V",
            "men": "Normale",
            "pass": "Centro",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "SI",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "DMC": "↓", "MC": "—", "AMC": "↑", "ST": "—"},
            "w": "ND risponde al loro 1-1: centro contro centro. AMC marca il loro AMC"
        },
        "debole": {
            "mod": "3-1-4-1-1",
            "alt": "4-3N-2W-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "AMC": "↑", "ST": "—"},
            "w": "Specchia la loro formazione con più qualità. Tutte le frecce avanti"
        }
    },
    {
        "av": "3W-1-4-1-1",
        "cat": "att",
        "meta": True,
        "forte": {
            "mod": "3-5-2 V",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DC": "↓", "ML": "—", "MC": "—", "MR": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "4 MC avversari affollano il centro. 5 MF bilancia il numero"
        },
        "pari": {
            "mod": "4-5-1 V",
            "alt": "4-3N-2W-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Sfrutta fasce scoperte. Il loro 1 AMC va marcato da DMC"
        },
        "debole": {
            "mod": "3-5-2 V",
            "alt": "4-3N-2W-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "Domina il centrocampo poi apri sulle fasce. Nessun terzino = spazio enorme"
        }
    },
    {
        "av": "4-1-3N-1-1",
        "cat": "neu",
        "meta": True,
        "forte": {
            "mod": "4-5-1 V",
            "alt": "3-2-2-2-1 B",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "★ META: 4-1-3-1-1 molto forte. DMC marca il loro AMC. Sfrutta le fasce con AML/AMR"
        },
        "pari": {
            "mod": "3-1-4-1-1",
            "alt": "4-5-1 V",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "DMC": "↓", "ML": "—", "MC": "—", "MR": "—", "AMC": "↑", "ST": "—"},
            "w": "★ Contro meta: usa 3-1-4-1-1 anche tu. 4 MC + AMC vs loro 3 MC + AMC"
        },
        "debole": {
            "mod": "3-1-4-2",
            "alt": "3-5-2 V",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "4 MC + DMC in avanti domina il loro 3N+AMC. Sfonda sulle fasce"
        }
    },
    {
        "av": "4-1-3W-1-1",
        "cat": "neu",
        "meta": True,
        "forte": {
            "mod": "5-1(DMC)-2-2",
            "alt": "4-5-1 F",
            "men": "Difensiva",
            "pass": "Misto",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Easy",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "5 difensori + DMC schermo bloccano le 3 ali avversarie. AML/AMR in contropiede"
        },
        "pari": {
            "mod": "4-4-1-1",
            "alt": "4-1-4-1",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "ML/MR coprono le loro 3W ali. AMC dietro è la minaccia: marcalo"
        },
        "debole": {
            "mod": "3-1-4-1-1",
            "alt": "4-4-1-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "AMC": "↑", "ST": "—"},
            "w": "4 MC con forza sulle fasce: sovrasta il loro 1 MC solo. DMC in avanti"
        }
    },
    {
        "av": "3-1-3-2-1 (Tiki-taka)",
        "cat": "att",
        "meta": True,
        "forte": {
            "mod": "4-5-1 V",
            "alt": "4-1-2-1-2 ND",
            "men": "Difensiva",
            "pass": "Centro",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "★ LevelWinner 2024: Tiki-taka senza terzini. Blocca centro e sfrutta fasce in contropiede"
        },
        "pari": {
            "mod": "4-3N-2W-1",
            "alt": "4-5-1 V",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Le fasce sono libere: 3 DC senza terzini. Aggredisci con AML/AMR"
        },
        "debole": {
            "mod": "4-3N-3",
            "alt": "4-3N-2W-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "MC": "↑", "ST": "—"},
            "w": "3 attaccanti vs loro 3 DC soli: superiorità numerica in attacco"
        }
    },
    {
        "av": "3-1-3-1-2 (Route One)",
        "cat": "att",
        "meta": True,
        "forte": {
            "mod": "3-5-2 F",
            "alt": "4-5-1 V",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "—", "MC": "—", "MR": "—", "ST": "—"},
            "w": "★ LevelWinner 2024: Route One su fasce vuote. 5 MF bilancia il loro centrocampo"
        },
        "pari": {
            "mod": "4-5-1 V",
            "alt": "3-5-2 F",
            "men": "Normale",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "—", "DC": "↓", "DR": "—", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Sfrutta le fasce: i loro ML/MR sono bassi (posizione difensiva). AML/AMR liberi"
        },
        "debole": {
            "mod": "3-5-2 V",
            "alt": "4-3N-2W-1",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Aggredisci sulle fasce con 5 MF. Il loro AMC resta isolato tra le linee"
        }
    },

    # ═══════════════════════════════
    # 🛡️ VS DIFENSIVI (5 difensori)
    # ═══════════════════════════════
    {
        "av": "5-4-1 F",
        "cat": "dif",
        "forte": {
            "mod": "4-3N-2W-1",
            "alt": "4-3N-3",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "MC": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Bus park: usa pazienza. Terzini alti sfruttano lo spazio tra i loro 5"
        },
        "pari": {
            "mod": "4-4-2 C",
            "alt": "4-3N-2W-1",
            "men": "Attaccante",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "↑"},
            "w": "ST con freccia avanti per occupare la difesa a 5. ML/MR sfruttano le fasce"
        },
        "debole": {
            "mod": "3-5-2 F",
            "alt": "4-4-2 C",
            "men": "Hard Att.",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "↑"},
            "w": "Aggredisci da subito: il bus si sfascia sotto pressione continua alta"
        }
    },
    {
        "av": "5-3N-2",
        "cat": "dif",
        "forte": {
            "mod": "4-4-2 C",
            "alt": "4-5-1 V",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "↑"},
            "w": "3 MC al centro: usa le fasce dove sono completamente scoperti"
        },
        "pari": {
            "mod": "3N-4-1-2",
            "alt": "4-4-2 C",
            "men": "Attaccante",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "—", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "Pazienza + variazioni tra centro e fasce. DMC neutro per equilibrio"
        },
        "debole": {
            "mod": "3N-4-1-2",
            "alt": "3-5-2 F",
            "men": "Hard Att.",
            "pass": "Fasce",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "↑"},
            "w": "Sovrasta: 4 MC + 2 ST contro 3 MC. Dominio assoluto sulle fasce"
        }
    },
    {
        "av": "5-3W-2",
        "cat": "dif",
        "forte": {
            "mod": "4-4-2 C",
            "alt": "4-3N-2W-1",
            "men": "Offensiva",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "↑", "DC": "↓", "DR": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "↑"},
            "w": "Ali larghe avversarie: attacca per il centro dove sono sguarniti"
        },
        "pari": {
            "mod": "3N-4-1-2",
            "alt": "4-4-2 C",
            "men": "Attaccante",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "4 MC martellano il centro: 5-3W-2 non ha DMC di protezione. DMC in avanti"
        },
        "debole": {
            "mod": "3N-5-2 V",
            "alt": "3-5-2 F",
            "men": "Hard Att.",
            "pass": "Centro",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Hard",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "5 MC dominano il centro. Le loro 3W restano alte e inutili sotto pressing"
        }
    },
    {
        "av": "5-2-1-2 X",
        "cat": "dif",
        "forte": {
            "mod": "4-1-2N-1-2",
            "alt": "4-5-1 V",
            "men": "Offensiva",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "SI",
            "fr": {"DL": "↓", "DC": "↓", "DR": "↓", "DMC": "—", "MC": "↑", "AMC": "↑", "ST": "—"},
            "w": "X-Style con DML/DMR: gioca stretto al centro. DMC neutro per gestire"
        },
        "pari": {
            "mod": "3N-1-4-2",
            "alt": "4-1-2N-1-2",
            "men": "Attaccante",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↓", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "—"},
            "w": "4 MC vs loro 1 AMC: dominio assoluto al centro"
        },
        "debole": {
            "mod": "3N-1-4-2",
            "alt": "3-5-2 F",
            "men": "Hard Att.",
            "pass": "Centro",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Hard",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "ST": "↑"},
            "w": "Sbaraglia il loro 1 AMC con 4 MC. DMC in avanti. Nessuno scampo"
        }
    },
    {
        "av": "4-3W-2N-1 XT (Xmas Tree)",
        "cat": "neu",
        "forte": {
            "mod": "3W-2(DMC)-3N-1-1",
            "alt": "4-5-1 F",
            "men": "Difensiva",
            "pass": "Centro",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Easy",
            "marc": "Zona",
            "fuo": "NO",
            "fr": {"DC": "↓", "DMC": "↓", "MC": "—", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "Tower + 2 DMC schermo vs Xmas Tree. AML/AMR pronti al contropiede"
        },
        "pari": {
            "mod": "3-1-5-1",
            "alt": "4-5-1 F",
            "men": "Normale",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↓", "ML": "—", "MC": "—", "MR": "—", "AML": "—", "AMR": "—", "ST": "—"},
            "w": "5 MF affolla il centro vs loro 3N+2AMC. Nessun DMC avversario"
        },
        "debole": {
            "mod": "3-1-5-1",
            "alt": "4-3N-3",
            "men": "Offensiva",
            "pass": "Centro",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DC": "↓", "DMC": "↑", "ML": "↑", "MC": "↑", "MR": "↑", "AML": "↑", "AMR": "↑", "ST": "—"},
            "w": "XT senza DMC: il centro è completamente aperto. Sfonda con tutto"
        }
    },
    # ═══════════════════════════════════════════════════════════
    # ⚡ VS 3-1-5-1 AMC (NUOVA META 2025 - Multi-Variante)
    # ═══════════════════════════════════════════════════════════
    {
        "av": "3-1-5-1 AMC",
        "cat": "neu",
        "meta": True,
        "forte": {
            "mod": "4-3-3",
            "alt": "4-2-3-1",
            "men": "Difensiva",
            "pass": "Fasce",
            "stile": "Lunghi",
            "ctrl": "SI",
            "press": "Basso",
            "cont": "Norm",
            "marc": "Uomo",
            "fuo": "SI",
            "fr": {"DL": "↓", "DC": "↓", "DC2": "↓", "DR": "↓", "MC": "↓", "MC2": "—", "MC3": "—", "ST": "↑", "AML": "↑", "AMR": "↑"},
            "w": "★ VS 3-1-5-1 FORTE: Marca a uomo l'AMC! Chiudi il centro, contropiede sulle fasce libere. MR-ML veloci per sfruttare 3 difensori"
        },
        "pari": {
            "mod": "4-2-3-1",
            "alt": "4-4-2 Flat",
            "men": "Normale",
            "pass": "Misto",
            "stile": "Misto",
            "ctrl": "NO",
            "press": "Normale",
            "cont": "Norm",
            "marc": "Zona",
            "fuo": "SI",
            "fr": {"DL": "—", "DC": "↓", "DC2": "↓", "DR": "—", "DMC": "↓", "DMC2": "—", "AML": "↑", "AMC": "↑", "AMR": "↑", "ST": "—"},
            "w": "VS 3-1-5-1 PARI: Il loro AMC è il perno - limita il suo spazio. Usa 2 DMC per schermarlo. Attacca le fasce: solo 3 difensori!"
        },
        "debole": {
            "mod": "4-3-3",
            "alt": "3-5-2",
            "men": "Offensiva",
            "pass": "Fasce",
            "stile": "Corti",
            "ctrl": "NO",
            "press": "Alto",
            "cont": "Duro",
            "marc": "Uomo",
            "fuo": "NO",
            "fr": {"DL": "↑", "DC": "—", "DC2": "—", "DR": "↑", "MC": "↑", "MC2": "↑", "MC3": "↑", "ST": "↑", "AML": "↑", "AMR": "↑"},
            "w": "★ VS 3-1-5-1 DEBOLE: Pressing totale! Solo 3 DC + 1 DMC. Superiorità numerica ovunque. Attacca le fasce con DL/DR avanti!"
        }
    }
]

# Legacy COUNTER_TACTICS for backward compatibility (converted from COUNTER_ENGINE)
COUNTER_TACTICS = []
for ce in COUNTER_ENGINE:
    tactic = {
        "formation": ce["av"],
        "category": ce["cat"],
        "meta": ce.get("meta", False),
        "scenarios": {
            "forte": ce["forte"],
            "pari": ce["pari"],
            "debole": ce["debole"]
        }
    }
    COUNTER_TACTICS.append(tactic)

# Also expose the full COUNTER_ENGINE for the new v6 UI
COUNTER_ENGINE_DATA = COUNTER_ENGINE
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
    },
    {
        "id": "17",
        "category": "counter",
        "title_en": "How to Beat 4-4-2 Classic",
        "title_it": "Come Battere il 4-4-2 Classico",
        "content_en": "Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Attack the flanks to exploit the absence of wide midfielders.",
        "content_it": "Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Attacca le fasce per sfruttare l'assenza di centrocampisti laterali."
    },
    {
        "id": "18",
        "category": "counter",
        "title_en": "How to Beat 4-3-3",
        "title_it": "Come Battere il 4-3-3",
        "content_en": "Best counter: 4-4-2. Setup — Mentality: Defensive, Focus Passing: Mixed, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: Yes. Tip: Use the four-man midfield to dominate central space.",
        "content_it": "Miglior contromodulo: 4-4-2. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Misto, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: Sì. Consiglio: Usa il centrocampo a quattro per dominare lo spazio centrale."
    },
    {
        "id": "19",
        "category": "counter",
        "title_en": "How to Beat 4-2-3-1",
        "title_it": "Come Battere il 4-2-3-1",
        "content_en": "Best counter: 4-1-3N-2. Setup — Mentality: Defensive, Focus Passing: Through the Middle, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: Yes. Tip: A DMC is vital for more clean sheets against this formation.",
        "content_it": "Miglior contromodulo: 4-1-3N-2. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Al Centro, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: Sì. Consiglio: Un DMC è vitale per ottenere più clean sheet contro questo modulo."
    },
    {
        "id": "20",
        "category": "counter",
        "title_en": "How to Beat 4-5-1 V-Style",
        "title_it": "Come Battere il 4-5-1 V-Style",
        "content_en": "Best counter: 4-3N-3. Setup — Mentality: Defensive, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Protect your flanks and attack theirs.",
        "content_it": "Miglior contromodulo: 4-3N-3. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Proteggi i tuoi fianchi e attacca quelli dell'avversario."
    },
    {
        "id": "21",
        "category": "counter",
        "title_en": "How to Beat 4-5-1 Flat",
        "title_it": "Come Battere il 4-5-1 Flat",
        "content_en": "Best counter: 4-1-4-1. Setup — Mentality: Normal, Focus Passing: Mixed, Passing: Short, Pressing: Medium, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Keep possession to neutralize their crowded midfield.",
        "content_it": "Miglior contromodulo: 4-1-4-1. Impostazioni — Mentalità: Normale, Focus Passaggi: Misto, Passaggi: Corto, Pressing: Medio, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Mantieni il possesso palla per neutralizzare il loro centrocampo folto."
    },
    {
        "id": "22",
        "category": "counter",
        "title_en": "How to Beat 3-5-2 Flat",
        "title_it": "Come Battere il 3-5-2 Flat",
        "content_en": "Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Exploit the wide weakness of the three-man defense with fast wingers.",
        "content_it": "Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Sfrutta la debolezza laterale della difesa a tre con ali veloci."
    },
    {
        "id": "23",
        "category": "counter",
        "title_en": "How to Beat 5-4-1 Flat",
        "title_it": "Come Battere il 5-4-1 Flat",
        "content_en": "Best counter: 4-4-2. Setup — Mentality: Attacking, Focus Passing: Mixed, Passing: Short, Pressing: High, Tackling: Normal, Marking: Man-to-Man, Offside Trap: No. Tip: Raise your line and pressing to break down the defensive wall.",
        "content_it": "Miglior contromodulo: 4-4-2. Impostazioni — Mentalità: Offensivo, Focus Passaggi: Misto, Passaggi: Corto, Pressing: Alto, Contrasti: Normale, Marcatura: A Uomo, Trappola Fuorigioco: No. Consiglio: Alza il baricentro e il pressing per scardinare il muro difensivo."
    },
    {
        "id": "24",
        "category": "counter",
        "title_en": "How to Beat 4-1-2-1-2 Narrow Diamond",
        "title_it": "Come Battere il 4-1-2-1-2 Narrow Diamond",
        "content_en": "Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Stretch play to bypass the density of the central diamond.",
        "content_it": "Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Allarga il gioco per aggirare la densità del rombo centrale."
    },
    {
        "id": "25",
        "category": "counter",
        "title_en": "How to Beat 4-2-2-2 Hexagon",
        "title_it": "Come Battere il 4-2-2-2 Hexagon",
        "content_en": "Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Wingers are essential to hit this versatile formation.",
        "content_it": "Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Le ali sono fondamentali per colpire questo modulo versatile."
    },
    {
        "id": "26",
        "category": "counter",
        "title_en": "How to Beat 3-4-1-2",
        "title_it": "Come Battere il 3-4-1-2",
        "content_en": "Best counter: 4-1-2-1-2 ND. Setup — Mentality: Normal, Focus Passing: Through the Middle, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Man-to-Man, Offside Trap: No. Tip: Attack the sides of the CBs if the opponent has no wide players.",
        "content_it": "Miglior contromodulo: 4-1-2-1-2 ND. Impostazioni — Mentalità: Normale, Focus Passaggi: Al Centro, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Uomo, Trappola Fuorigioco: No. Consiglio: Attacca i lati dei DC se l'avversario non ha ali laterali."
    },
    {
        "id": "27",
        "category": "counter",
        "title_en": "How to Beat 3-4-3",
        "title_it": "Come Battere il 3-4-3",
        "content_en": "Best counter: 4-2-2-2 Hexagon. Setup — Mentality: Defensive, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Exploit the open space on the flanks of the three-man defense.",
        "content_it": "Miglior contromodulo: 4-2-2-2 Hexagon. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Sfrutta lo spazio aperto sulle fasce della difesa a tre."
    },
    {
        "id": "28",
        "category": "counter",
        "title_en": "How to Beat 4-1-3-2 Wide",
        "title_it": "Come Battere il 4-1-3-2 Wide",
        "content_en": "Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Mixed, Passing: Short, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Keep balance between the lines so you're not caught out.",
        "content_it": "Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Misto, Passaggi: Corto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Mantieni l'equilibrio tra le linee per non farti sorprendere."
    },
    {
        "id": "29",
        "category": "counter",
        "title_en": "How to Beat 5-2-1-2 X-Style",
        "title_it": "Come Battere il 5-2-1-2 X-Style",
        "content_en": "Best counter: 4-1-2-1-2 ND. Setup — Mentality: Normal, Focus Passing: Mixed, Passing: Mixed, Pressing: High, Tackling: Normal, Marking: Man-to-Man, Offside Trap: No. Tip: Intensify pressing to win the ball back quickly.",
        "content_it": "Miglior contromodulo: 4-1-2-1-2 ND. Impostazioni — Mentalità: Normale, Focus Passaggi: Misto, Passaggi: Misto, Pressing: Alto, Contrasti: Normale, Marcatura: A Uomo, Trappola Fuorigioco: No. Consiglio: Intensifica il pressing per recuperare palla velocemente."
    },
    {
        "id": "30",
        "category": "scenario",
        "title_en": "Defending a Lead",
        "title_it": "In Vantaggio",
        "content_en": "When you hold a comfortable lead, switch to a defensive or 'park-the-bus' mentality using formations like the 5-4-1. Lower the pressing and set zonal marking to protect the result and conserve energy.",
        "content_it": "Se hai un vantaggio rassicurante, passa a una mentalità difensiva o 'Park-the-Bus' usando moduli come il 5-4-1. Riduci il pressing a basso e imposta la marcatura zonale per proteggere il risultato e conservare energia."
    },
    {
        "id": "31",
        "category": "scenario",
        "title_en": "Chasing the Game",
        "title_it": "In Svantaggio",
        "content_en": "Around the 60th minute, switch to aggressive formations like the 4-2-4 or 3-4-1-2 to add attacking weight. Turn on high pressing and man-to-man marking to force errors and win the ball back quickly.",
        "content_it": "Intorno al 60° minuto, passa a formazioni aggressive come il 4-2-4 o il 3-4-1-2 per aumentare il peso offensivo. Attiva il pressing alto e la marcatura a uomo per forzare l'avversario all'errore e recuperare palla velocemente."
    },
    {
        "id": "32",
        "category": "scenario",
        "title_en": "Managing the 90 Minutes",
        "title_it": "Gestione dei Tempi",
        "content_en": "Start the match with low pressing to preserve your key players' fitness. In the second half, raise the intensity and bring on a striker or winger from the bench if you need decisive late goals.",
        "content_it": "Inizia il match con pressing basso per conservare la condizione fisica dei tuoi giocatori chiave. Nel secondo tempo, aumenta l'intensità e inserisci un attaccante o un'ala dalla panchina se hai bisogno di segnare gol decisivi nel finale."
    },
    {
        "id": "33",
        "category": "scenario",
        "title_en": "Quick Tactical Switches",
        "title_it": "Cambi Tattici Rapidi",
        "content_en": "Save up to four different formations in the Team menu for instant tactical switches during the live match. This lets you react to the opponent's moves without wasting precious time or unnecessary substitutions.",
        "content_it": "Salva fino a quattro formazioni diverse nel menu Squadra per effettuare cambi tattici istantanei durante il match live. Questa strategia ti permette di reagire alle mosse dell'avversario senza sprecare tempo prezioso o sostituzioni inutili."
    },
    {
        "id": "34",
        "category": "morale",
        "title_en": "Morale Baseline",
        "title_it": "Baseline del Morale",
        "content_en": "The 'Good' morale level is now the new baseline and is more impactful than the old 'Superb'. Always check the Morale tab to see if players need more game time or if events like a hat-trick have boosted their state.",
        "content_it": "Il livello di morale 'Buono' è ora il nuovo standard di base ed è più impattante del vecchio 'Superbo'. Controlla sempre il tab Morale per capire se i giocatori necessitano di più minutaggio o se eventi come una tripletta hanno aumentato il loro stato."
    },
    {
        "id": "35",
        "category": "morale",
        "title_en": "Condition & Pressing",
        "title_it": "Condizione e Pressing",
        "content_en": "Avoid turning on high pressing too early so you don't drain fitness before the last 10 minutes. Condition that drops too low drastically reduces player effectiveness in the crucial phases of the match.",
        "content_it": "Evita di attivare il pressing alto troppo presto nel match per non esaurire la condizione fisica prima degli ultimi 10 minuti. Una condizione troppo bassa riduce drasticamente l'efficacia dei giocatori nelle fasi cruciali della partita."
    },
    {
        "id": "36",
        "category": "morale",
        "title_en": "Team Balance",
        "title_it": "Equilibrio di Squadra",
        "content_en": "Keep your Team Balance score between 9.2 and 10 to ensure the team performs at its peak. Having a single overpowered ('mutant') player can paradoxically lower overall quality and lead to losses against weaker teams.",
        "content_it": "Mantieni il punteggio di 'Team Balance' tra 9.2 e 10 per garantire che la squadra performi al massimo delle sue potenzialità. Avere un singolo giocatore 'overpowered' (mutante) può paradossalmente abbassare la qualità complessiva e portare a sconfitte contro team più deboli."
    },
    {
        "id": "37",
        "category": "market",
        "title_en": "Hunting Fast Trainers",
        "title_it": "Ricerca Fast Trainers",
        "content_en": "At auctions, focus on buying 'fast trainers' who grow quickly with training. Following specific lists of these talents lets you build a competitive squad while saving tokens and resources.",
        "content_it": "Durante le aste, concentrati sull'acquisto di giocatori definiti 'fast trainers' che crescono rapidamente con l'allenamento. Seguire liste specifiche di questi talenti ti permette di costruire una squadra competitiva risparmiando token e risorse."
    },
    {
        "id": "38",
        "category": "market",
        "title_en": "Stockpiling Tokens",
        "title_it": "Accumulo di Token",
        "content_en": "Use the daily Special Sponsor and free events like the Draw Frenzy to stockpile tokens without spending real money. A good token reserve is essential to reinforce key roles during the hot phases of the season.",
        "content_it": "Sfrutta quotidianamente lo Special Sponsor e gli eventi gratuiti come il 'Draw Frenzy' per accumulare token senza spendere denaro reale. Una buona riserva di token è fondamentale per rinforzare i ruoli chiave durante le fasi calde della stagione."
    },
    {
        "id": "39",
        "category": "market",
        "title_en": "Auction Strategy",
        "title_it": "Strategia nelle Aste",
        "content_en": "Carefully analyze a player's 'white' attributes before bidding, favoring those with very high key stats and low 'grey' stats. Don't rebid compulsively — judge whether the token cost is justified by the player's growth potential.",
        "content_it": "Analizza attentamente le abilità 'bianche' di un giocatore prima di offrire, preferendo chi ha statistiche chiave altissime e statistiche 'grigie' basse. Non rilanciare compulsivamente, ma valuta se il costo in token è giustificato dal potenziale di crescita del giocatore."
    },
    {
        "id": "40",
        "category": "skills",
        "title_en": "The False Nine Dominance",
        "title_it": "Il Dominio del Falso Nove",
        "content_en": "In the 2026 meta the False Nine is considered the strongest striker playstyle. It lets the forward drop deep, dragging out the centre-backs and creating lethal gaps for the wingers' runs.",
        "content_it": "Nel meta 2026, il False Nine è considerato lo stile di gioco più forte per un attaccante. Questo ruolo permette alla punta di arretrare, attirando fuori i difensori centrali e creando varchi letali per gli inserimenti delle ali."
    },
    {
        "id": "41",
        "category": "skills",
        "title_en": "Wingers & Dual Position",
        "title_it": "Ali e Doppio Ruolo",
        "content_en": "Use players with the Dual Position ability (AML/AMR) to exploit weaknesses in opposing defenses. Wingers are essential to overload the flanks against formations that defend poorly out wide, like the 4-5-1 V-Style.",
        "content_it": "Utilizza giocatori con abilità 'Dual Position' (AML/AMR) per sfruttare i punti deboli delle difese avversarie. Le ali sono essenziali per sovraccaricare le fasce contro moduli che difendono male lateralmente, come il 4-5-1 V-Style."
    },
    {
        "id": "42",
        "category": "skills",
        "title_en": "Arrows & Pace",
        "title_it": "Frecce e Velocità",
        "content_en": "Apply the red (forward) arrow to fast players to push them forward, and the blue (back) arrow to slower ones to keep them in defensive position. This trick optimizes the team's dynamic positioning based on each player's physical traits.",
        "content_it": "Applica la freccia rossa ai giocatori con alta velocità per spingerli in fase offensiva e la freccia blu a quelli più lenti per mantenerli in posizione difensiva. Questo trucco ottimizza il posizionamento dinamico della squadra in base alle caratteristiche fisiche dei singoli."
    },
    {
        "id": "43",
        "category": "skills",
        "title_en": "Shadow Striker Role",
        "title_it": "Ruolo Shadow Striker",
        "content_en": "Set up an AMC with the Shadow Striker ability to create a 'hidden' threat that breaks into the empty spaces left by the defense. This is especially effective when the opponent has no DMC protecting the area in front of the back line.",
        "content_it": "Imposta un AMC con l'abilità Shadow Striker per creare una minaccia 'segreta' che si inserisce negli spazi vuoti lasciati dalla difesa. Questa posizione è particolarmente efficace se l'avversario non utilizza un DMC per proteggere l'area davanti ai difensori."
    },
    {
        "id": "44",
        "category": "skills",
        "title_en": "DMC for Clean Sheets",
        "title_it": "DMC per i Clean Sheet",
        "content_en": "Adding a DMC is vital in almost any formation to increase your chance of a clean sheet. Acting as an 'advanced stopper', he screens the defense and intercepts the play of the opponent's most dangerous AMCs.",
        "content_it": "L'inserimento di un DMC è vitale in quasi ogni formazione per aumentare la probabilità di non subire gol. Agendo come uno 'stopper avanzato', scherma la difesa e intercetta le trame di gioco degli AMC avversari più pericolosi."
    }
]

# ==================== PLAYER ROLES DATA ====================

PLAYER_ROLES = [
    {
        "id": "sweeper-keeper",
        "position": "GK",
        "name_en": "Sweeper Keeper",
        "name_it": "Portiere Libero",
        "key_attributes_en": ["Reflexes", "Aerial Ability", "Positioning"],
        "key_attributes_it": ["Riflessi", "Uscite", "Posizionamento"],
        "best_formations": ["4-5-1", "4-3-3"],
        "training_focus_en": "Saving, Reflexes, Aerial Ability",
        "training_focus_it": "Parata, Riflessi, Uscite",
        "description_en": "Participates in build-up and covers the space behind a high defensive line.",
        "description_it": "Partecipa alla manovra e copre lo spazio dietro la difesa alta."
    },
    {
        "id": "ball-playing-defender",
        "position": "DC",
        "name_en": "Ball-Playing Defender",
        "name_it": "Difensore Regista",
        "key_attributes_en": ["Passing", "Marking", "Creativity"],
        "key_attributes_it": ["Passaggio", "Marcatura", "Creatività"],
        "best_formations": ["3-5-2", "4-3-3"],
        "training_focus_en": "Passing, Marking, Positioning",
        "training_focus_it": "Passaggio, Marcatura, Posizionamento",
        "description_en": "Essential for clean ball progression under opponent pressing.",
        "description_it": "Fondamentale per l'uscita pulita del pallone sotto pressing avversario."
    },
    {
        "id": "no-nonsense-centre-back",
        "position": "DC",
        "name_en": "No-Nonsense Centre-Back",
        "name_it": "Difensore Puro",
        "key_attributes_en": ["Tackling", "Marking", "Strength"],
        "key_attributes_it": ["Contrasto", "Marcatura", "Forza"],
        "best_formations": ["4-4-2", "5-4-1"],
        "training_focus_en": "Strength, Marking, Tackling",
        "training_focus_it": "Forza, Marcatura, Contrasto",
        "description_en": "Focuses purely on defending without risking difficult passes.",
        "description_it": "Si concentra solo sulla difesa senza rischiare passaggi difficili."
    },
    {
        "id": "full-back",
        "position": "DL/DR",
        "name_en": "Full-Back",
        "name_it": "Terzino",
        "key_attributes_en": ["Tackling", "Marking", "Pace"],
        "key_attributes_it": ["Contrasto", "Marcatura", "Velocità"],
        "best_formations": ["4-1-2-1-2 ND", "4-4-2"],
        "training_focus_en": "Tackling, Marking, Positioning",
        "training_focus_it": "Contrasto, Marcatura, Posizionamento",
        "description_en": "Provides defensive solidity on the flanks against strong opposing wingers.",
        "description_it": "Garantisce solidità difensiva sulle fasce contro ali avversarie forti."
    },
    {
        "id": "wing-back",
        "position": "DL/DR",
        "name_en": "Wing-Back",
        "name_it": "Terzino Fluidificante",
        "key_attributes_en": ["Crossing", "Pace", "Tackling"],
        "key_attributes_it": ["Cross", "Velocità", "Contrasto"],
        "best_formations": ["3-5-2", "4-5-1 V-Style"],
        "training_focus_en": "Crossing, Pace, Tackling",
        "training_focus_it": "Cross, Velocità, Contrasto",
        "description_en": "Pushes up with a forward arrow to give width and cross for the strikers.",
        "description_it": "Spinge con freccia SU per dare ampiezza e crossare per le punte."
    },
    {
        "id": "inverted-wing-back",
        "position": "DL/DR",
        "name_en": "Inverted Wing-Back",
        "name_it": "Terzino Invertito",
        "key_attributes_en": ["Passing", "Tackling", "Positioning"],
        "key_attributes_it": ["Passaggio", "Contrasto", "Posizionamento"],
        "best_formations": ["4-3-3", "4-1-4-1"],
        "training_focus_en": "Passing, Tackling, Dribbling",
        "training_focus_it": "Passaggio, Contrasto, Dribbling",
        "description_en": "Tucks into midfield to help control central possession.",
        "description_it": "Entra in mezzo al campo per aiutare la gestione del possesso centrale."
    },
    {
        "id": "anchor-man",
        "position": "DMC",
        "name_en": "Anchor Man",
        "name_it": "Incontrista Arretrato",
        "key_attributes_en": ["Tackling", "Positioning", "Strength"],
        "key_attributes_it": ["Contrasto", "Posizionamento", "Forza"],
        "best_formations": ["4-1-4-1", "4-5-1 V-Style"],
        "training_focus_en": "Tackling, Marking, Positioning",
        "training_focus_it": "Contrasto, Marcatura, Posizionamento",
        "description_en": "The 'advanced stopper' vital to shield the defense and earn clean sheets.",
        "description_it": "Lo 'stopper avanzato' vitale per proteggere la difesa e fare clean sheet."
    },
    {
        "id": "deep-lying-playmaker",
        "position": "DMC",
        "name_en": "Deep-Lying Playmaker",
        "name_it": "Regista Arretrato",
        "key_attributes_en": ["Passing", "Creativity", "Tackling"],
        "key_attributes_it": ["Passaggio", "Creatività", "Contrasto"],
        "best_formations": ["4-3-3", "4-1-2-1-2 ND"],
        "training_focus_en": "Passing, Creativity, Tackling",
        "training_focus_it": "Passaggio, Creatività, Contrasto",
        "description_en": "Deep playmaker who distributes the ball and builds play from the back.",
        "description_it": "Playmaker basso che smista palloni e costruisce gioco dalle retrovie."
    },
    {
        "id": "box-to-box-midfielder",
        "position": "MC",
        "name_en": "Box-to-Box Midfielder",
        "name_it": "Centrocampista Totale",
        "key_attributes_en": ["Stamina", "Passing", "Tackling"],
        "key_attributes_it": ["Resistenza", "Passaggio", "Contrasto"],
        "best_formations": ["4-4-2", "4-5-1 Flat"],
        "training_focus_en": "Passing, Strength, Stamina",
        "training_focus_it": "Passaggio, Forza, Resistenza",
        "description_en": "Tireless midfield engine operating between both penalty boxes.",
        "description_it": "Instancabile motore del centrocampo che agisce tra le due aree di rigore."
    },
    {
        "id": "mezzala",
        "position": "MC",
        "name_en": "Mezzala",
        "name_it": "Mezzala",
        "key_attributes_en": ["Shooting", "Pace", "Dribbling"],
        "key_attributes_it": ["Tiro", "Velocità", "Dribbling"],
        "best_formations": ["4-3-3", "4-1-3-1-1"],
        "training_focus_en": "Shooting, Pace, Finishing",
        "training_focus_it": "Tiro, Velocità, Finalizzazione",
        "description_en": "Late-running forward who attacks the half-spaces to finish in the box.",
        "description_it": "Incursore che attacca gli half-spaces per concludere l'azione in porta."
    },
    {
        "id": "advanced-playmaker",
        "position": "AMC",
        "name_en": "Advanced Playmaker",
        "name_it": "Regista Avanzato",
        "key_attributes_en": ["Creativity", "Passing", "Shooting"],
        "key_attributes_it": ["Creatività", "Passaggio", "Tiro"],
        "best_formations": ["4-2-3-1", "3-4-1-2"],
        "training_focus_en": "Passing, Creativity, Shooting",
        "training_focus_it": "Passaggio, Creatività, Tiro",
        "description_en": "The creative hub who delivers killer assists between the lines.",
        "description_it": "Il faro della manovra offensiva che serve assist letali tra le linee."
    },
    {
        "id": "wide-midfielder",
        "position": "ML/MR",
        "name_en": "Wide Midfielder",
        "name_it": "Esterno di Centrocampo",
        "key_attributes_en": ["Crossing", "Passing", "Stamina"],
        "key_attributes_it": ["Cross", "Passaggio", "Resistenza"],
        "best_formations": ["4-4-2", "4-5-1 Flat"],
        "training_focus_en": "Crossing, Passing, Marking",
        "training_focus_it": "Cross, Passaggio, Marcatura",
        "description_en": "Provides balance and a constant supply for the strikers.",
        "description_it": "Garantisce equilibrio e rifornimenti costanti per gli attaccanti."
    },
    {
        "id": "classic-winger",
        "position": "AML/AMR",
        "name_en": "Classic Winger",
        "name_it": "Ala Classica",
        "key_attributes_en": ["Crossing", "Pace", "Dribbling"],
        "key_attributes_it": ["Cross", "Velocità", "Dribbling"],
        "best_formations": ["4-3-3", "4-5-1 V-Style"],
        "training_focus_en": "Crossing, Pace, Dribbling",
        "training_focus_it": "Cross, Velocità, Dribbling",
        "description_en": "Exploits the Dual Position Advantage to beat his man and cross.",
        "description_it": "Sfrutta il Dual Position Advantage per saltare l'uomo e crossare."
    },
    {
        "id": "inverted-winger",
        "position": "AML/AMR",
        "name_en": "Inverted Winger",
        "name_it": "Ala Invertita",
        "key_attributes_en": ["Shooting", "Dribbling", "Pace"],
        "key_attributes_it": ["Tiro", "Dribbling", "Velocità"],
        "best_formations": ["4-2-3-1", "4-3-3"],
        "training_focus_en": "Shooting, Finishing, Dribbling",
        "training_focus_it": "Tiro, Finalizzazione, Dribbling",
        "description_en": "Cuts inside to shoot with his inverted foot toward goal.",
        "description_it": "Taglia verso il centro per calciare col piede invertito verso la porta."
    },
    {
        "id": "target-man",
        "position": "ST",
        "name_en": "Target Man",
        "name_it": "Centravanti Boa",
        "key_attributes_en": ["Heading", "Strength", "Finishing"],
        "key_attributes_it": ["Colpo di testa", "Forza", "Finalizzazione"],
        "best_formations": ["4-4-2", "4-5-1 Flat"],
        "training_focus_en": "Heading, Strength, Finishing",
        "training_focus_it": "Colpo di testa, Forza, Finalizzazione",
        "description_en": "Physical reference for crosses; wins aerial duels against defenders.",
        "description_it": "Riferimento fisico per i cross; vince i duelli aerei contro i difensori."
    },
    {
        "id": "poacher",
        "position": "ST",
        "name_en": "Poacher",
        "name_it": "Uomo d'Area",
        "key_attributes_en": ["Finishing", "Anticipation", "Shooting"],
        "key_attributes_it": ["Finalizzazione", "Riflessi", "Tiro"],
        "best_formations": ["4-1-2-1-2 ND", "3-5-2"],
        "training_focus_en": "Finishing, Shooting, Pace",
        "training_focus_it": "Finalizzazione, Tiro, Velocità",
        "description_en": "Lethal in the final yards, always in the right place at the right time.",
        "description_it": "Letale negli ultimi metri, si fa trovare sempre al posto giusto."
    },
    {
        "id": "complete-forward",
        "position": "ST",
        "name_en": "Complete Forward",
        "name_it": "Attaccante Completo",
        "key_attributes_en": ["Finishing", "Shooting", "Passing"],
        "key_attributes_it": ["Finalizzazione", "Tiro", "Passaggio"],
        "best_formations": ["4-3-3", "4-4-2"],
        "training_focus_en": "Finishing, Shooting, Heading",
        "training_focus_it": "Finalizzazione, Tiro, Colpo di testa",
        "description_en": "Universal player able to score, assist and hold up the ball.",
        "description_it": "Giocatore universale capace di segnare, assistere e proteggere palla."
    },
    {
        "id": "false-9",
        "position": "ST",
        "name_en": "False 9",
        "name_it": "Falso Nove",
        "key_attributes_en": ["Passing", "Shooting", "Creativity"],
        "key_attributes_it": ["Passaggio", "Tiro", "Creatività"],
        "best_formations": ["4-5-1 V-Style", "4-3-3"],
        "training_focus_en": "Passing, Shooting, Creativity",
        "training_focus_it": "Passaggio, Tiro, Creatività",
        "description_en": "Strongest playstyle of the 2026 meta: drops deep to free up runners.",
        "description_it": "Playstyle più forte del meta 2026: si abbassa per liberare inserimenti."
    },
    {
        "id": "pressing-forward",
        "position": "ST",
        "name_en": "Pressing Forward",
        "name_it": "Attaccante di Pressing",
        "key_attributes_en": ["Stamina", "Pace", "Tackling"],
        "key_attributes_it": ["Resistenza", "Velocità", "Contrasto"],
        "best_formations": ["4-1-4-1", "4-3-3"],
        "training_focus_en": "Pace, Strength, Stamina",
        "training_focus_it": "Velocità, Forza, Resistenza",
        "description_en": "The team's first defender; harasses defenders during build-up.",
        "description_it": "Primo difensore della squadra; aggredisce i difensori in costruzione."
    }
]

# ==================== META TACTICS 2026 DATA ====================

META_TACTICS = [
    {
        "id": "4-5-1-v-style",
        "formation": "4-5-1 V-Style",
        "tier": "S",
        "why_it_works_en": "Considered the most versatile formation of 2026, able to adapt to any opponent.",
        "why_it_works_it": "Considerata la formazione più versatile del 2026, capace di adattarsi a ogni avversario.",
        "setup_en": "Normal or defensive mentality, AML/AMR wingers and a DMC vital for defensive cover.",
        "setup_it": "Mentalità normale o difensiva, ali AML/AMR e un DMC vitale per la copertura difensiva.",
        "counter_en": "Effectively countered with the 4-3N-3 or the 3N-2-3N-2.",
        "counter_it": "Si contrasta efficacemente con il 4-3N-3 o il 3N-2-3N-2."
    },
    {
        "id": "4-3-3",
        "formation": "4-3-3",
        "tier": "S",
        "why_it_works_en": "Dominates the attacking phase through the lethal synergy between a False Nine and fast wingers.",
        "why_it_works_it": "Domina la fase offensiva sfruttando la sinergia letale tra False Nine e ali veloci.",
        "setup_en": "Requires the False Nine playstyle and an attacking mentality with passing focused down the flanks.",
        "setup_it": "Richiede il playstyle False Nine e mentalità offensiva con focus passaggi sulle fasce.",
        "counter_en": "Beaten with the 4-4-2 or 4-1-3-1-1 for defensive solidity.",
        "counter_it": "Si batte con il 4-4-2 o il 4-1-3-1-1 per solidità difensiva."
    },
    {
        "id": "4-1-2-1-2-nd",
        "formation": "4-1-2-1-2 ND",
        "tier": "S",
        "why_it_works_en": "Excels at total midfield control and fast ball-carrying transitions.",
        "why_it_works_it": "Eccelle nel controllo totale del centrocampo e nelle transizioni rapide palla al piede.",
        "setup_en": "Uses red arrows on the STs and AMC with passing focused strictly through the middle.",
        "setup_it": "Prevede frecce rosse su ST e AMC con passaggi focalizzati rigorosamente al centro.",
        "counter_en": "The ideal counter is the 4-5-1 V-Style to stretch the play.",
        "counter_it": "Il counter ideale è il 4-5-1 V-Style per allargare il gioco."
    },
    {
        "id": "3-1-5-1",
        "formation": "3-1-5-1",
        "tier": "A",
        "why_it_works_en": "A 'secret' formation that overloads midfield, making the opponent's build-up impossible.",
        "why_it_works_it": "Formazione 'segreta' che sovraccarica la mediana rendendo impossibile la manovra nemica.",
        "setup_en": "Requires high pressing, an attacking mentality and a solid DMC to screen the back three.",
        "setup_it": "Richiede pressing alto, mentalità offensiva e un DMC solido per schermare la difesa a tre.",
        "counter_en": "Countered with direct attacks down the flanks or with the 3-5-2 V.",
        "counter_it": "Si contrasta con attacchi diretti sulle fasce o con il 3-5-2 V."
    },
    {
        "id": "4-2-3-1",
        "formation": "4-2-3-1",
        "tier": "A",
        "why_it_works_en": "Ideal for keeping possession and hurting opposing defenses that lack a DMC.",
        "why_it_works_it": "Ideale per mantenere il possesso e colpire difese avversarie sprovviste di un DMC.",
        "setup_en": "Uses an attacking mentality, short passing and a creative AMC to feed the lone striker.",
        "setup_it": "Usa mentalità offensiva, passaggi corti e un AMC creativo per servire l'unica punta.",
        "counter_en": "The best counter is the 4-1-3N-2 with a deep defensive line.",
        "counter_it": "Il miglior counter è il 4-1-3N-2 con difesa arretrata."
    },
    {
        "id": "4-2-2-2-hexagon",
        "formation": "4-2-2-2 Hexagon",
        "tier": "A",
        "why_it_works_en": "A very balanced formation, called 'fashionable' for its excellent pitch coverage.",
        "why_it_works_it": "Formazione molto equilibrata e definita 'di moda' per la sua ottima copertura del campo.",
        "setup_en": "Uses two DMCs for stability and wide players to supply the two central strikers.",
        "setup_it": "Utilizza due DMC per la stabilità e ali larghe per rifornire i due attaccanti centrali.",
        "counter_en": "Countered with the 3-4-3 or the 4-5-1 V-Style.",
        "counter_it": "Si contrasta con il 3-4-3 o con il 4-5-1 V-Style."
    },
    {
        "id": "4-1-3-1-1",
        "formation": "4-1-3-1-1",
        "tier": "B",
        "why_it_works_en": "Provides superior defensive protection, ideal for earning clean sheets.",
        "why_it_works_it": "Fornisce una protezione difensiva superiore, ideale per ottenere partite a porta inviolata.",
        "setup_en": "Deploys a deep DMC and MCs to handle strong strikers and midfielders.",
        "setup_it": "Prevede DMC e MC in posizione arretrata per gestire attaccanti e centrocampisti forti.",
        "counter_en": "Beaten by formations that overload its MCs, like the 4-5-1 V.",
        "counter_it": "Si batte usando formazioni che sovraccaricano i suoi MC, come il 4-5-1 V."
    },
    {
        "id": "4-1-4-1",
        "formation": "4-1-4-1",
        "tier": "B",
        "why_it_works_en": "An excellent formation to neutralize the opposing midfield and control the tempo.",
        "why_it_works_it": "Formazione eccellente per neutralizzare il centrocampo avversario e gestire il ritmo.",
        "setup_en": "Requires a defensive/normal mentality and a DMC with a blue arrow to close every gap.",
        "setup_it": "Richiede mentalità difensiva/normale e un DMC con freccia blu per chiudere ogni spazio.",
        "counter_en": "Beaten with the 4-2-2-2 Hexagon to break its rigidity.",
        "counter_it": "Si batte con il 4-2-2-2 Hexagon per spezzare la sua rigidità."
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
    """Get all counter tactics (legacy format)"""
    return COUNTER_TACTICS

@api_router.get("/counters/{formation_id}")
async def get_counter_for_formation(formation_id: str):
    """Get counter tactics for a specific formation (legacy format)"""
    for counter in COUNTER_TACTICS:
        if counter["formation"] == formation_id:
            return counter
    raise HTTPException(status_code=404, detail="Counter tactics not found")

@api_router.get("/counter-engine")
async def get_counter_engine():
    """Get all Counter Engine v6 data with full details"""
    return COUNTER_ENGINE_DATA

@api_router.get("/counter-engine/{av}")
async def get_counter_engine_for_formation(av: str):
    """Get Counter Engine v6 data for a specific opponent formation"""
    for ce in COUNTER_ENGINE_DATA:
        if ce["av"] == av:
            return ce
    raise HTTPException(status_code=404, detail="Counter engine data not found")

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

# ==================== PLAYER ROLES ENDPOINTS ====================

@api_router.get("/player-roles")
async def get_player_roles():
    """Get all player roles"""
    return PLAYER_ROLES

@api_router.get("/player-roles/{role_id}")
async def get_player_role(role_id: str):
    """Get a specific player role by id, or filter by position code"""
    # Exact role id match
    for role in PLAYER_ROLES:
        if role["id"] == role_id:
            return role
    # Fallback: treat the path param as a position filter (e.g. ST, DC, AMC)
    by_position = [
        role for role in PLAYER_ROLES
        if role_id.upper() in [p.strip().upper() for p in role["position"].split("/")]
    ]
    if by_position:
        return by_position
    raise HTTPException(status_code=404, detail="Player role not found")

# ==================== META TACTICS ENDPOINTS ====================

@api_router.get("/meta-tactics")
async def get_meta_tactics():
    """Get the 2026 meta tactics tier list"""
    return META_TACTICS

@api_router.get("/meta-tactics/{tier}")
async def get_meta_tactics_by_tier(tier: str):
    """Get meta tactics filtered by tier (S, A, B)"""
    items = [m for m in META_TACTICS if m["tier"].upper() == tier.upper()]
    if not items:
        raise HTTPException(status_code=404, detail="No meta tactics found for this tier")
    return items

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
async def ai_chat(chat_request: ChatRequest):
    """AI-powered tactics assistant - No auth required for Wiki mode"""
    
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="AI service not configured")
    
    # Get language-specific system message
    if chat_request.language == 'it':
        system_message = """Sei un esperto assistente tattico per Top Eleven, il gioco di calcio manageriale. 
        Aiuti i giocatori con:
        - Suggerimenti su formazioni e tattiche META 2025/2026
        - Contro-tattiche per battere avversari più forti
        - Consigli su acquisti e scout giocatori
        - Strategie di allenamento e gestione rosa
        - Tips per vincere campionati e coppe
        
        Rispondi sempre in italiano in modo chiaro e conciso. Mantieni le risposte brevi (max 3-4 paragrafi).
        Usa formazioni specifiche (es. 3-1-4-1-1, 4-5-1 V-Style) quando possibile."""
    else:
        system_message = """You are an expert tactical assistant for Top Eleven, the football manager game.
        You help players with:
        - META 2025/2026 formation and tactics suggestions
        - Counter-tactics to beat stronger opponents
        - Player scouting and transfer advice
        - Training strategies and squad management
        - Tips for winning leagues and cups
        
        Always respond in English, clearly and concisely. Keep responses short (max 3-4 paragraphs).
        Use specific formations (e.g., 3-1-4-1-1, 4-5-1 V-Style) when possible."""
    
    try:
        # Initialize chat with unique session
        session_id = f"top11_wiki_{datetime.now().timestamp()}"
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=system_message
        )
        chat.with_model("openai", "gpt-4o")
        
        # Send message
        user_message = UserMessage(text=chat_request.message)
        response = await chat.send_message(user_message)
        
        return {"response": response}
        
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        raise HTTPException(status_code=500, detail=f"AI service error: {str(e)}")

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
