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
        'id': '442c',
        'name': '4-4-2 C (Classic)',
        'description_en': 'Classic balanced formation. Strong in both defense and attack with 4 defenders, 4 midfielders, and 2 strikers. One of the oldest and most reliable formations in football.',
        'description_it': 'Formazione bilanciata classica. Forte in ampiezza. 4 difensori, 4 centrocampisti e 2 attaccanti.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'MR', 'MC', 'MC', 'ML', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Balanced', 'Good width', 'Partnership up front', 'Simple to execute'],
        'strengths_it': ['Equilibrata', 'Buona ampiezza', 'Partnership in attacco', 'Semplice da eseguire'],
        'weaknesses_en': ['Can be outnumbered in midfield', 'Requires fit wingers'],
        'weaknesses_it': ['Può essere superata numericamente a centrocampo', 'Richiede ali in forma'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciato',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Short',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact and let them come. Use long balls to your strikers on counter.',
                'tip_it': 'Resta compatto e lasciali venire. Usa palle lunghe agli attaccanti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Play your natural game. Use width and crosses to find your two strikers.',
                'tip_it': "Gioca il tuo gioco naturale. Usa l'ampiezza e i cross per trovare i due attaccanti.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Dominate with high pressing and quick passing. Overwhelm their defense with numbers.',
                'tip_it': 'Domina con pressing alto e passaggi veloci. Travolgi la loro difesa con i numeri.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-2-2-2-1 B (Butterfly)', '4-1-2-1-2 ND (Narrow Diamond)'],
        'effective_against': [
            '3-1-4-2',
            '4-2-2-1-1',
            '4-3-3',
            '5-1-1-1-2',
            '5-1DMC-2-2',
            '5-2-2(AML-AMR)-1',
            '5-2-3',
            '5-2W-2N-1',
            '5-3-2',
            '5-3N-2',
            '5-4-1 F (Flat)',
            '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'
        ]
    },
    {
        'id': '41212nd',
        'name': '4-1-2-1-2 ND (Narrow Diamond)',
        'description_en': 'Narrow diamond midfield formation. Strong through the center with DMC protecting defense and AMC linking play. Flanks are vulnerable - attack down the wings against this.',
        'description_it': 'Diamond stretto. DMC protegge la difesa e AMC collega il gioco. I fianchi sono vulnerabili: attacca sulle ali contro questa formazione.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'DMC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Central dominance', 'Creative #10', 'Two striker partnership', 'Good passing lanes'],
        'strengths_it': [
            'Dominio centrale',
            'Trequartista creativo',
            'Partnership di due attaccanti',
            'Buone linee di passaggio'
        ],
        'weaknesses_en': ['No natural wingers', 'Exposed flanks', 'Requires box-to-box midfielders'],
        'weaknesses_it': ['Nessuna ala naturale', 'Fianchi esposti', 'Richiede centrocampisti box-to-box'],
        'tactic_type_en': 'Possession / Central Attack',
        'tactic_type_it': 'Possesso / Attacco Centrale',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'Normal',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'DMC shields the back 4. Long balls to striker partnership on counters.',
                'tip_it': "Il DMC protegge la difesa a 4. Palle lunghe alla coppia d'attacco in contropiede.",
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Control the center and let AMC create for the 2 strikers. Be patient.',
                'tip_it': "Controlla il centro e lascia che l'AMC crei per i 2 attaccanti. Sii paziente.",
                'arrows': {
                    'DL': '↓',
                    'DC': '↓',
                    'DR': '↓',
                    'AMC': '↑',
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Dominate the center completely. Your AMC should feast on their weak midfield.',
                'tip_it': 'Domina il centro completamente. Il tuo AMC deve banchettare sul loro centrocampo debole.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3N-5-2 V', '4-5-1 V-Style'],
        'effective_against': ['3-1-4-1-1', '3-4-1-2', '4-4-2 C (Classic)']
    },
    {
        'id': '41212wd',
        'name': '4-1-2-1-2 WD (Wide Diamond)',
        'description_en': 'Wide diamond with high AML/AMR. More width than narrow diamond but vulnerable in the center.',
        'description_it': 'Diamond largo. AML/AMR alti. Vulnerabile nel centro.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'DMC', 'AML', 'AMR', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Width in attack', 'Creative AMC', 'Two strikers', 'Flexible wingers'],
        'strengths_it': ['Ampiezza in attacco', 'AMC creativo', 'Due attaccanti', 'Ali flessibili'],
        'weaknesses_en': ['Vulnerable center', 'No central midfield', 'Exposed to central attacks'],
        'weaknesses_it': ['Centro vulnerabile', 'Nessun centrocampo centrale', 'Esposta ad attacchi centrali'],
        'tactic_type_en': 'Attacking / Wide',
        'tactic_type_it': 'Attaccante / Largo',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact. Use AML/AMR pace on counters to find strikers.',
                'tip_it': 'Resta compatto. Usa la velocità di AML/AMR in contropiede per trovare gli attaccanti.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Use width with AML/AMR. AMC links play between midfield and strikers.',
                'tip_it': "Usa l'ampiezza con AML/AMR. L'AMC collega centrocampo e attaccanti.",
                'arrows': {
                    'ST': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'AMC': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Push AML/AMR high. Overload their flanks with width and crosses.',
                'tip_it': 'Spingi AML/AMR in alto. Sovraccarica le loro fasce con ampiezza e cross.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1'],
        'effective_against': []
    },
    {
        'id': '451v',
        'name': '4-5-1 V-Style',
        'description_en': 'Excellent defensive formation with V-shaped midfield (DMC-2MC-AML-AMR). Perfect counter-attacking setup. META choice against possession teams and narrow diamonds.',
        'description_it': 'Eccellente formazione difensiva con centrocampo a V (DMC-2MC-AML-AMR). Setup perfetto per il contropiede. Scelta META contro squadre di possesso e diamanti stretti.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': [
            'Solid 4-man defense',
            'Numerical midfield advantage',
            'Wide attacks from AML/AMR',
            'Counters 4-4-2 perfectly',
            'V-shape controls space'
        ],
        'strengths_it': [
            'Difesa solida a 4',
            'Vantaggio numerico a centrocampo',
            'Attacchi larghi da AML/AMR',
            'Contrasta perfettamente il 4-4-2',
            'Forma a V controlla lo spazio'
        ],
        'weaknesses_en': ['Lone striker isolated', 'Requires pace on wings', 'Can be too defensive'],
        'weaknesses_it': [
            'Attaccante solitario isolato',
            'Richiede velocità sulle fasce',
            'Può essere troppo difensiva'
        ],
        'tactic_type_en': '★ META 2026 / Counter-Attack',
        'tactic_type_it': '★ META 2026 / Contropiede',
        'arrows': 'DMC↓ AML↑ AMR↑',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Sulle Fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': 'Park the bus! Let them attack, hit on counter with AML/AMR speed. DMC↓ to shield DCs.',
                'tip_it': 'Parcheggia il bus! Lascia che attacchino, colpisci in contropiede con velocità AML/AMR. DMC↓ per schermare DC.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': True,
                'tip_en': 'V-shape gives control. Push AML/AMR↑ for attack width. Counter when they overcommit.',
                'tip_it': 'La forma a V dà controllo. Spingi AML/AMR↑ per ampiezza. Contropiede quando si sbilanciano.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Sulle Fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Dominate wings! DL/DR↑ overlap. AML/AMR become wingers. Overload their flanks.',
                'tip_it': 'Domina le fasce! DL/DR↑ sovrapposizione. AML/AMR diventano ali. Sovraccarica le loro fasce.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-3N-3'],
        'effective_against': [
            '3-1-3-1-2',
            '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
            '3W-2DMC-3W-1-1 ML (Maple Leaf)',
            '4-1-1-3-1',
            '4-1-2-1-2 ND (Narrow Diamond)',
            '4-1-3-1-1',
            '4-2-2-2 H (Hexagon)',
            '4-3-1-2'
        ]
    },
    {
        'id': '451f',
        'name': '4-5-1 F (Flat)',
        'description_en': '5 flat midfielders. Great for counter-attacking and controlling possession. Defensive but lethal on breaks.',
        'description_it': '5 centrocampisti piatti. Buono in contropiede e controllo possesso. Difensivo ma letale nelle ripartenze.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'MR', 'MC', 'MC', 'MC', 'ML', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['5-man midfield', 'Counter-attack', 'Defensive solidity', 'Width control'],
        'strengths_it': ['Centrocampo a 5', 'Contropiede', 'Solidità difensiva', 'Controllo ampiezza'],
        'weaknesses_en': ['Lone striker isolated', 'Limited attack', 'Predictable'],
        'weaknesses_it': ['Attaccante isolato', 'Attacco limitato', 'Prevedibile'],
        'tactic_type_en': 'Counter-Attack / Defensive',
        'tactic_type_it': 'Contropiede / Difensivo',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Mixed',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': '5 flat midfielders block everything. Counter with long balls to lone ST.',
                'tip_it': '5 centrocampisti piatti bloccano tutto. Contropiede con palle lunghe al ST solitario.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Control midfield with 5 players. Wait for counter opportunities.',
                'tip_it': 'Controlla il centrocampo con 5 giocatori. Aspetta occasioni di contropiede.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'DL': '↑',
                    'DR': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Push wide midfielders up. Use width to create for the lone striker.',
                'tip_it': "Spingi gli esterni in alto. Usa l'ampiezza per creare per l'attaccante solitario.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-5-2 F (Flat)', '3-5-2 V (V-Style)', '4-1-4-1'],
        'effective_against': ['4-3-2-1 XT (Xmas Tree)']
    },
    {
        'id': '4231',
        'name': '4-2-3-1',
        'description_en': 'Modern tactical formation with 2 MCs and 3 attacking mids behind lone striker. ★ Defensive arrows on 3DC, ML and MR.',
        'description_it': 'Formazione tattica moderna con 2 MC e 3 trequartisti dietro attaccante solitario. ★ Frecce difensive a 3DC, ML e MR.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Defensive stability', 'Creative playmaker', 'Compact midfield', 'Flexible'],
        'strengths_it': ['Stabilità difensiva', 'Regista creativo', 'Centrocampo compatto', 'Flessibile'],
        'weaknesses_en': ['Lone striker isolated', 'Depends heavily on AMC', 'Can lack width'],
        'weaknesses_it': ['Attaccante solitario isolato', "Dipende molto dall'AMC", 'Può mancare ampiezza'],
        'tactic_type_en': 'Balanced / Counter-Attack',
        'tactic_type_it': 'Bilanciato / Contropiede',
        'arrows': '★ DC↓ DL↓ DR↓ ML↓ MR↓',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': '2 MCs protect defense. Use AMC to link play on counter-attacks.',
                'tip_it': "2 MC proteggono la difesa. Usa l'AMC per collegare in contropiede.",
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Let AMC orchestrate attacks. Use AML/AMR width to create for the lone striker.',
                'tip_it': "Lascia l'AMC orchestrare gli attacchi. Usa AML/AMR per creare per l'attaccante.",
                'arrows': {
                    'AMC': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Push your AML/AMR high. Overload their defense with creative play through AMC.',
                'tip_it': "Spingi AML/AMR in avanti. Sovraccarica la difesa con gioco creativo dall'AMC.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-1-4-2', '4-1-4-1', '5-4-1 F (Flat)'],
        'effective_against': ['3-1-4-2 W', '3-1-5-1 AMC']
    },
    {
        'id': '4222h',
        'name': '4-2-2-2 H (Hexagon)',
        'description_en': 'Compact Hexagon formation with 2 MCs, 2 AMs, and 2 strikers. ★ Arrows forward on DL, DR, AML, AMR.',
        'description_it': 'Formazione compatta Hexagon con 2 MC, 2 trequartisti e 2 attaccanti. ★ Frecce avanti a DL, DR, AML, AMR.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'MC', 'MC', 'AML', 'AMR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Central control', 'Two partnerships', 'Compact shape', 'Transitions well'],
        'strengths_it': ['Controllo centrale', 'Due partnership', 'Forma compatta', 'Buone transizioni'],
        'weaknesses_en': ['Lacks width', 'No natural wingers', 'Predictable'],
        'weaknesses_it': ['Manca ampiezza', 'Nessuna ala naturale', 'Prevedibile'],
        'tactic_type_en': 'Central / Transition',
        'tactic_type_it': 'Centrale / Transizione',
        'arrows': '★ DL↑ DR↑ AML↑ AMR↑',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact in center. Use the 2 striker partnership to hold the ball on counters.',
                'tip_it': "Resta compatto al centro. Usa la coppia d'attacco per tenere palla nei contropiedi.",
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Control center with compact shape. AML/AMR drift in to support strikers.',
                'tip_it': 'Controlla il centro con la forma compatta. AML/AMR accentrarsi per supportare gli attaccanti.',
                'arrows': {
                    'MC': '↓',
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Overwhelm center! Your 4 central attackers should dominate their midfield.',
                'tip_it': 'Travolgi il centro! I tuoi 4 attaccanti centrali devono dominare il loro centrocampo.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-5-1 V-Style'],
        'effective_against': ['3-4-3', '3-5-2 V (V-Style)', '4-1-2-2-1', '4-1-4-1']
    },
    {
        'id': '352f',
        'name': '3-5-2 F (Flat)',
        'description_en': "Midfield-dominant with 5 flat midfielders. No full-backs - exploit opponent's free wings against this formation.",
        'description_it': 'Dominante a centrocampo con 5 centrocampisti piatti. Nessun terzino - sfrutta le ali libere del rivale.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'MR', 'MC', 'MC', 'MC', 'ML', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Midfield control', 'Numerical advantage in center', 'Partnership up front'],
        'strengths_it': ['Controllo del centrocampo', 'Vantaggio numerico al centro', 'Partnership in attacco'],
        'weaknesses_en': ['Exposed flanks', 'No full-backs', 'Weak against wide formations'],
        'weaknesses_it': ['Fianchi esposti', 'Nessun terzino', 'Debole contro formazioni ampie'],
        'tactic_type_en': 'Attacking / High Press',
        'tactic_type_it': 'Attaccante / Pressing Alto',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Mixed',
            'passing_style': 'Long',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Man-to-Man',
            'offside_trap': True
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Keep 5 midfielders tight. Counter through striker partnership.',
                'tip_it': "Tieni i 5 centrocampisti stretti. Contropiede attraverso la coppia d'attacco.",
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Dominate midfield with 5 players. ML/MR overlap for width.',
                'tip_it': 'Domina il centrocampo con 5 giocatori. ML/MR sovrappongono per ampiezza.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'All-out attack with 7 players forward. Overwhelm their defense!',
                'tip_it': 'Attacco totale con 7 giocatori in avanti. Travolgi la loro difesa!',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-3-3', '4-3N-2W-1'],
        'effective_against': ['3-1-3-1-2', '3-4-1-2', '4-5-1 F (Flat)', '5-4-1 F (Flat)']
    },
    {
        'id': '352v',
        'name': '3-5-2 V (V-Style)',
        'description_en': 'V-style 3-5-2 with high AML/AMR. Effective against crowded midfield but open wings.',
        'description_it': '3-5-2 V-style con AML/AMR alti. Efficace contro centrocampo affollato ma ali scoperte.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['High wingers', 'Midfield control', 'Two strikers', 'Pressing'],
        'strengths_it': ['Ali alte', 'Controllo centrocampo', 'Due attaccanti', 'Pressing'],
        'weaknesses_en': ['Exposed 3 CBs', 'No full-backs', 'Vulnerable on flanks'],
        'weaknesses_it': ['3 DC esposti', 'Nessun terzino', 'Vulnerabile sulle fasce'],
        'tactic_type_en': 'Attacking / Wide High',
        'tactic_type_it': 'Attaccante / Ali Alte',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': True,
                'tip_en': 'High AML/AMR exploit space on counters. Protect 3 CBs.',
                'tip_it': 'AML/AMR alti sfruttano spazi in contropiede. Proteggi i 3 DC.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Use width with AML/AMR. Strike partnership creates chances.',
                'tip_it': "Usa l'ampiezza con AML/AMR. La coppia d'attacco crea occasioni.",
                'arrows': {
                    'ST': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Push AML/AMR very high. Overwhelm with 5 attackers!',
                'tip_it': 'Spingi AML/AMR molto in alto. Travolgi con 5 attaccanti!',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-2-2-2 H (Hexagon)', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': ['3-1-3-1-2', '3W-1-3N-1-2', '4-1-4-1', '4-5-1 F (Flat)']
    },
    {
        'id': '3142',
        'name': '3-1-4-2',
        'description_en': 'DMC anchors the midfield with 4 wide midfielders. Strong against 4-3-3 and formations with 3 attackers.',
        'description_it': 'DMC ancora il centrocampo con 4 centrocampisti larghi. Forte contro 4-3-3 e formazioni con 3 attaccanti.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['DMC protection', 'Wide midfield', 'Two strikers', 'Counter 4-3-3'],
        'strengths_it': ['Protezione DMC', 'Centrocampo ampio', 'Due attaccanti', 'Contrasta 4-3-3'],
        'weaknesses_en': ['3 CBs exposed', 'Needs fit ML/MR', 'Vulnerable to counters'],
        'weaknesses_it': ['3 DC esposti', 'Richiede ML/MR in forma', 'Vulnerabile ai contropiedi'],
        'tactic_type_en': 'Counter-Attack / Anti-433',
        'tactic_type_it': 'Contropiede / Anti-433',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Mixed',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Man-to-Man',
            'offside_trap': True
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'DMC shields 3 CBs. Long balls to striker partnership on counters.',
                'tip_it': "Il DMC protegge i 3 DC. Palle lunghe alla coppia d'attacco in contropiede.",
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high with 4 midfielders. DMC covers. Strike on transitions.',
                'tip_it': 'Pressa alto con 4 centrocampisti. Il DMC copre. Colpisci nelle transizioni.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Push ML/MR high as extra attackers. Overwhelm with 6 in attack!',
                'tip_it': 'Spingi ML/MR in alto come attaccanti extra. Travolgi con 6 in attacco!',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3-4-3', '4-4-2 C (Classic)'],
        'effective_against': ['4-2-3-1']
    },
    {
        'id': '541f',
        'name': '5-4-1 F (Flat)',
        'description_en': 'Classic parked bus. 5 defenders + 4 flat midfielders. Counter-attack lethal. Maximum defensive solidity.',
        'description_it': 'Bus parcheggiato classico. 5 difensori + 4 centrocampisti piatti. Contropiede letale. Massima solidità difensiva.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'MR', 'MC', 'MC', 'ML', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Maximum defense', 'Hard to break down', 'Lethal counter', '5 at back'],
        'strengths_it': ['Massima difesa', 'Difficile da penetrare', 'Contropiede letale', '5 in difesa'],
        'weaknesses_en': ['Very limited attack', 'Lone striker', 'Can invite pressure'],
        'weaknesses_it': ['Attacco molto limitato', 'Attaccante solitario', 'Può invitare la pressione'],
        'tactic_type_en': 'Ultra Defensive / Bus Parking',
        'tactic_type_it': 'Ultra Difensivo / Catenaccio',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'FULL CATENACCIO! 5-4-1 deep and compact. Long balls to lone striker on rare counters.',
                'tip_it': "CATENACCIO TOTALE! 5-4-1 profondo e compatto. Palle lunghe all'attaccante nei rari contropiedi.",
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay organized. Let wing-backs push when safe. Target lone striker.',
                'tip_it': "Resta organizzato. Lascia sovrapporre gli esterni quando è sicuro. Punta l'attaccante solitario.",
                'arrows': {
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Push wing-backs higher to create. You can be more adventurous.',
                'tip_it': 'Spingi gli esterni più in alto per creare. Puoi essere più avventuroso.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['3-5-2 F (Flat)', '4-3N-2W-1', '4-4-2 C (Classic)'],
        'effective_against': [
            '3-1-2-1-3',
            '3-1-3-2W-1',
            '3-1-4-1-1',
            '3-1-4-2 W',
            '3-3-1-3',
            '3-4-3',
            '3-5-2 V (V-Style)',
            '3N-1-2-1-3',
            '4-1-1-3-1',
            '4-2-1-3',
            '4-2-3-1',
            '4-2-3-1 Attack',
            '4-2-4',
            'False Nine + Wingers'
        ]
    },
    {
        'id': '32221b',
        'name': '3-2-2-2-1 B (Butterfly)',
        'description_en': 'Defensive Butterfly formation. Double AMC creates chances for lone striker.',
        'description_it': "Butterfly difensivo. Doppio trequartista crea occasioni per l'attaccante solitario.",
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Double playmakers', 'Compact center', 'Counter-attack ready'],
        'strengths_it': ['Doppi registi', 'Centro compatto', 'Pronto al contropiede'],
        'weaknesses_en': ['No width', '3 CBs exposed', 'Needs quality AMCs'],
        'weaknesses_it': ['Nessuna ampiezza', '3 DC esposti', 'Richiede AMC di qualità'],
        'tactic_type_en': 'Defensive / Creative',
        'tactic_type_it': 'Difensivo / Creativo',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Mixed',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay deep. Double AMC links to ST on counters.',
                'tip_it': 'Resta profondo. Doppio AMC collega a ST in contropiede.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Control center with double AMC. Wait for counter opportunities.',
                'tip_it': 'Controlla il centro con doppio AMC. Aspetta occasioni di contropiede.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Push AMCs forward. Create chances through the middle.',
                'tip_it': 'Spingi gli AMC in avanti. Crea occasioni dal centro.',
                'arrows': {
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3-4-1-2', '4-3-3'],
        'effective_against': ['3N-5-2 V', '4-4-2 C (Classic)', '3W-2DMC-3W-1-1 ML (Maple Leaf)']
    },
    {
        'id': '3n2221b',
        'name': '3N-2-2-2-1 B (Butterfly 3N)',
        'description_en': 'Butterfly with 3 narrow defenders and double DMC. Great against formations with 3 DCs.',
        'description_it': 'Butterfly 3 difensori. Doppio DMC. Ottimo contro schemi con 3 DC.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Double DMC shield', 'Width with AML/AMR', 'Counter 3DC formations'],
        'strengths_it': ['Doppio scudo DMC', 'Ampiezza con AML/AMR', 'Contrasta formazioni 3DC'],
        'weaknesses_en': ['3 narrow CBs', 'Needs quality DMCs', 'Can be exposed on flanks'],
        'weaknesses_it': ['3 DC stretti', 'Richiede DMC di qualità', 'Può essere esposta sulle fasce'],
        'tactic_type_en': 'Attacking / Anti-3DC',
        'tactic_type_it': 'Attaccante / Anti-3DC',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Double DMC shields 3 CBs. Counter through AML/AMR to ST.',
                'tip_it': 'Doppio DMC protegge i 3 DC. Contropiede tramite AML/AMR verso ST.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Balance with double DMC. Use width with AML/AMR.',
                'tip_it': "Equilibrio con doppio DMC. Usa l'ampiezza con AML/AMR.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Push AML/AMR high. Overwhelm with width and pace!',
                'tip_it': 'Spingi AML/AMR in alto. Travolgi con ampiezza e velocità!',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-3N-2W-1'],
        'effective_against': []
    },
    {
        'id': '4141',
        'name': '4-1-4-1',
        'description_en': 'Classic defensive formation with single DMC shield. 4-man backline, 4 midfielders, 1 striker. Great for controlling games and counter-attacking against 4-4-2.',
        'description_it': 'Formazione difensiva classica con singolo scudo DMC. Linea difensiva a 4, 4 centrocampisti, 1 attaccante. Ottima per controllare le partite e contropiede contro 4-4-2.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MC', 'MR', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': [
            'Compact and solid',
            'DMC protects defense',
            'Wide coverage',
            'Easy live adjustments',
            'Counters 4-4-2 effectively'
        ],
        'strengths_it': [
            'Compatta e solida',
            'DMC protegge la difesa',
            'Copertura ampia',
            'Facili aggiustamenti live',
            'Contrasta efficacemente il 4-4-2'
        ],
        'weaknesses_en': ['Lone striker problem', 'Can lack creativity', 'MC overworked'],
        'weaknesses_it': ['Problema attaccante solitario', 'Può mancare creatività', 'MC sovraccaricati'],
        'tactic_type_en': 'META 2026 / Solid Defense',
        'tactic_type_it': 'META 2026 / Difesa Solida',
        'arrows': 'DMC↓',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Sulle Fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': 'Defend deep! DMC↓ always. ML/MR track back. Quick long balls to ST on counter.',
                'tip_it': 'Difendi basso! DMC↓ sempre. ML/MR rientrano. Lanci lunghi rapidi a ST in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': 'Control the game. DMC anchors defense. Push MC forward if winning.',
                'tip_it': 'Controlla la partita. DMC ancora la difesa. Spingi MC avanti se in vantaggio.',
                'arrows': {
                    'DL': '↓',
                    'DC': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Push everyone! DMC becomes MC, ML/MR become AML/AMR. Suffocate them.',
                'tip_it': 'Spingi tutti! DMC diventa MC, ML/MR diventano AML/AMR. Soffocali.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-5-2 V (V-Style)', '4-2-2-2 H (Hexagon)'],
        'effective_against': [
            '3-1-3-2W-1',
            '3-3-1-3',
            '3-4-2-1',
            '3W-1-3N-1-2',
            '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
            '3W-2DMC-3W-1-1 ML (Maple Leaf)',
            '4-1-1-2N-2',
            '4-1-2-1-2 WD (Wide Diamond)',
            '4-1-2-2-1',
            '4-1-3-1-1',
            '4-1-3-1W-1',
            '4-1-3N-2',
            '4-2-2-2 N (Narrow)',
            '4-2-3-1',
            '4-2-3-1-2',
            '4-2N-1-2N-1',
            '4-3-1-2',
            '4-3-2-1 XT (Xmas Tree)',
            '4-3N-3',
            '4-5-1 F (Flat)',
            '4-5-1 V-Style'
        ]
    },
    {
        'id': '433',
        'name': '4-3-3',
        'description_en': 'Attacking formation with 3 forwards. ★ Red arrows on AML, AMR, ST. 3 attackers press high, MCs fall back in defense.',
        'description_it': 'Formazione offensiva con 3 attaccanti. ★ Frecce rosse su AML, AMR, ST. 3 attaccanti, MC rientrano in difesa.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['High pressing', 'Width in attack', 'Creative midfield', 'Overloads flanks'],
        'strengths_it': ['Pressing alto', 'Ampiezza in attacco', 'Centrocampo creativo', 'Sovraccarica le fasce'],
        'weaknesses_en': ['Vulnerable to counters', 'Midfield can be overrun', '3 MCs must work hard'],
        'weaknesses_it': [
            'Vulnerabile ai contropiedi',
            'Centrocampo può essere sopraffatto',
            '3 MC devono lavorare duro'
        ],
        'tactic_type_en': 'High Press / Attacking',
        'tactic_type_it': 'Pressing Alto / Attaccante',
        'arrows': '★ AML↑ AMR↑ ST↑',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Man-to-Man',
            'offside_trap': True
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': True,
                'tip_en': "Don't overcommit. Use wingers to stretch their defense on counters.",
                'tip_it': 'Non esporti troppo. Usa le ali per allargare la difesa in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and dominate flanks. Your wingers are key to breaking them.',
                'tip_it': 'Pressa alto e domina le fasce. Le tue ali sono la chiave per sfondare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Full attack mode! Press relentlessly and overload their half.',
                'tip_it': 'Attacco totale! Pressa senza sosta e sovraccarica la loro metà campo.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-4-2 C (Classic)'],
        'effective_against': [
            '3-1-2-1-3',
            '3-1-3-2W-1',
            '3-1-4-1-1',
            '3-1-4-2 W',
            '3-1-5-1 AMC',
            '3-2-2-2-1 B (Butterfly)',
            '3-3-1-3',
            '3-4-2-1',
            '3-4-3',
            '3-5-2 F (Flat)',
            '3-5-2 V (V-Style)',
            '3N-1-2-1-3',
            '4-1-1-3-1',
            '4-2-1-3',
            '4-2-2-1-1',
            '4-2-2-2 N (Narrow)',
            '4-2-3-1 Attack',
            '4-2-3-1-2',
            '4-2-4',
            '5-1-1-1-2',
            '5-1DMC-2-2',
            '5-2-2(AML-AMR)-1',
            '5-2-3',
            '5-2W-2N-1',
            '5-3-2',
            'False Nine + Wingers'
        ]
    },
    {
        'id': '53n2',
        'name': '5-3N-2',
        'description_en': '5 defenders + 3 central MCs. Very solid against wing attacks.',
        'description_it': '5 difensori + 3 MC centrali. Solido contro ali.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'ST', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['5 defenders', 'Central control', 'Two strikers', 'Hard to break'],
        'strengths_it': ['5 difensori', 'Controllo centrale', 'Due attaccanti', 'Difficile da sfondare'],
        'weaknesses_en': ['No width', 'Wing-backs must overlap', 'Lacks creativity'],
        'weaknesses_it': ['Nessuna ampiezza', 'Gli esterni devono sovrapporre', 'Manca creatività'],
        'tactic_type_en': 'Ultra Defensive / Central',
        'tactic_type_it': 'Ultra Difensivo / Centrale',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': '5 defenders block everything. Long balls to striker duo on counters.',
                'tip_it': "5 difensori bloccano tutto. Palle lunghe alla coppia d'attacco in contropiede.",
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay deep and organized. Wing-backs push when safe.',
                'tip_it': 'Resta profondo e organizzato. Gli esterni spingono quando è sicuro.',
                'arrows': {
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Wing-backs push high. Use width to create for strikers.',
                'tip_it': "Gli esterni spingono in alto. Usa l'ampiezza per creare per gli attaccanti.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '343',
        'name': '3-4-3',
        'description_en': 'Ultra-attacking with 3 attackers and wide midfield. Good against 4-2-2-2 H. Overloads wide midfield.',
        'description_it': 'Ultra-offensiva con 3 attaccanti e centrocampo ampio. Contro 4-2-2-2 H. Sovraffolla il centrocampo largo.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MR', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['3 attackers', 'Width', 'Pressing intensity', 'Overwhelming offense'],
        'strengths_it': ['3 attaccanti', 'Ampiezza', 'Intensità del pressing', 'Attacco travolgente'],
        'weaknesses_en': ['3 CBs only', 'Vulnerable to counters', 'High stamina needed'],
        'weaknesses_it': ['Solo 3 DC', 'Vulnerabile ai contropiedi', 'Richiede alta resistenza'],
        'tactic_type_en': 'All-Out Attack',
        'tactic_type_it': 'Attacco Totale',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Man-to-Man',
            'offside_trap': True
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': True,
                'tip_en': 'RISKY! Use only if behind. Protect the 3 CBs on counters.',
                'tip_it': 'RISCHIOSO! Usa solo se in svantaggio. Proteggi i 3 DC nei contropiedi.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Attack is the best defense. Press high and force errors.',
                'tip_it': "L'attacco è la miglior difesa. Pressa alto e forza errori.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Destroy them! Full attack with 7 players forward!',
                'tip_it': 'Distruggili! Attacco totale con 7 giocatori in avanti!',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-2-2-2 H (Hexagon)', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': [
            '3-1-4-2',
            '3-4-2-1',
            '3W-1-3N-1-2',
            '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
            '3W-2DMC-3W-1-1 ML (Maple Leaf)',
            '4-1-1-2N-2',
            '4-1-2-1-2 WD (Wide Diamond)',
            '4-1-2-2-1',
            '4-1-3-1-1',
            '4-1-3-1W-1',
            '4-1-3N-2',
            '4-2-2-2 N (Narrow)',
            '4-2-3-1-2',
            '4-2N-1-2N-1',
            '4-3-1-2',
            '4-3-2-1 XT (Xmas Tree)',
            '4-3N-3',
            '4-5-1 V-Style'
        ]
    },
    {
        'id': '3w2dmc3w11ml',
        'name': '3W-2DMC-3W-1-1 ML (Maple Leaf)',
        'description_en': 'Maple Leaf formation. Wide AML/AMR with AMC as playmaker. Double DMC shield. Against 4-1-3W-2.',
        'description_it': 'Maple Leaf. AML/AMR larghi, AMC trequartista. Doppio DMC schermo. Contro 4-1-3W-2.',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Double DMC shield', 'Wide AML/AMR', 'Creative AMC', 'Flexible'],
        'strengths_it': ['Doppio scudo DMC', 'AML/AMR larghi', 'AMC creativo', 'Flessibile'],
        'weaknesses_en': ['3 CBs exposed', 'Complex to execute', 'Needs quality players'],
        'weaknesses_it': ['3 DC esposti', 'Complessa da eseguire', 'Richiede giocatori di qualità'],
        'tactic_type_en': 'Attacking / Creative',
        'tactic_type_it': 'Attaccante / Creativo',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Double DMC protects. Counter through wide AML/AMR to ST.',
                'tip_it': 'Doppio DMC protegge. Contropiede tramite AML/AMR larghi verso ST.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'AMC orchestrates. Use wide AML/AMR to create for ST.',
                'tip_it': "L'AMC orchestra. Usa AML/AMR larghi per creare per ST.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Full creative attack! AMC + wide players overwhelm!',
                'tip_it': 'Attacco creativo totale! AMC + esterni travolgono!',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3N-1-4-2', '4-5-1 V-Style', '3-2-2-2-1 B (Butterfly)'],
        'effective_against': []
    },
    {
        'id': '3w2dmc3n11tower',
        'name': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
        'description_en': 'Tower/Eiffel Tower formation. Two screening DMCs, AMC is the offensive tower.',
        'description_it': 'Tower: due DMC schermo, AMC torre offensiva.',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'DMC', 'MC', 'MC', 'MC', 'AMC', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Double DMC screen', 'AMC as tower', 'Creative play', 'Solid base'],
        'strengths_it': ['Doppio schermo DMC', 'AMC come torre', 'Gioco creativo', 'Base solida'],
        'weaknesses_en': ['3 CBs exposed', 'Complex', 'Needs quality AMC'],
        'weaknesses_it': ['3 DC esposti', 'Complessa', 'Richiede AMC di qualità'],
        'tactic_type_en': 'Attacking / Tower Style',
        'tactic_type_it': 'Attaccante / Stile Torre',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'Normal',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'DMC duo shields. AMC links to ST on quick counters.',
                'tip_it': 'Duo DMC protegge. AMC collega a ST in contropiedi veloci.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'AMC is the tower. Feed him and let him create for ST.',
                'tip_it': "L'AMC è la torre. Servilo e lascialo creare per ST.",
                'arrows': {
                    'AMC': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Push AMC high. Let the tower dominate in their half!',
                'tip_it': "Spingi l'AMC in alto. Lascia la torre dominare nella loro metà!",
                'arrows': {
                    'AMC': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-4-2 C (Classic)', '4-5-1 V-Style', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '51dmc22',
        'name': '5-1DMC-2-2',
        'description_en': '5 defenders + DMC screen. Against 4-1-3W-1-1 formations.',
        'description_it': '5 difensori + DMC schermo. Contro 4-1-3W-1-1.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'DMC', 'AML', 'AMR', 'ST', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['5 defenders', 'DMC shield', 'Two strikers', 'Counter ready'],
        'strengths_it': ['5 difensori', 'Scudo DMC', 'Due attaccanti', 'Pronto al contropiede'],
        'weaknesses_en': ['Very defensive', 'Limited midfield', 'AML/AMR isolated'],
        'weaknesses_it': ['Molto difensiva', 'Centrocampo limitato', 'AML/AMR isolati'],
        'tactic_type_en': 'Ultra Defensive / Counter',
        'tactic_type_it': 'Ultra Difensivo / Contropiede',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': '6 defenders! Long balls to striker duo on rare counters.',
                'tip_it': "6 difensori! Palle lunghe alla coppia d'attacco nei rari contropiedi.",
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay deep. Use AML/AMR on counters to find strikers.',
                'tip_it': 'Resta profondo. Usa AML/AMR in contropiede per trovare gli attaccanti.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Push AML/AMR high. Create for the striker duo.',
                'tip_it': "Spingi AML/AMR in alto. Crea per la coppia d'attacco.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['4-3-3', '4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '5212x',
        'name': '5-2-1-2 X (X-Style)',
        'description_en': 'X-Style with DML/DMR. Against 5-2-1-2 formations.',
        'description_it': 'X-Style con DML/DMR. Contro 5-2-1-2.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DC', 'DL', 'DML', 'DMR', 'AMC', 'ST', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['5 defenders', 'DML/DMR coverage', 'Counter ready', 'Hard to break'],
        'strengths_it': ['5 difensori', 'Copertura DML/DMR', 'Pronto al contropiede', 'Difficile da sfondare'],
        'weaknesses_en': ['Very defensive', 'Limited creativity', 'Needs fit DML/DMR'],
        'weaknesses_it': ['Molto difensiva', 'Creatività limitata', 'Richiede DML/DMR in forma'],
        'tactic_type_en': 'Ultra Defensive / X-Style',
        'tactic_type_it': 'Ultra Difensivo / X-Style',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Hard',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Full catenaccio! DML/DMR block midfield. Long to strikers.',
                'tip_it': 'Catenaccio totale! DML/DMR bloccano il centrocampo. Lungo agli attaccanti.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay organized. AMC links to strikers on counters.',
                'tip_it': 'Resta organizzato. AMC collega agli attaccanti in contropiede.',
                'arrows': {
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Push DML/DMR up. AMC orchestrates attacks to strikers.',
                'tip_it': 'Spingi DML/DMR in alto. AMC orchestra attacchi verso gli attaccanti.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': [],
        'effective_against': []
    },
    {
        'id': '522amlamr1',
        'name': '5-2-2(AML-AMR)-1',
        'description_en': '5 defenders with high wings. Against 4-2N-1-2W-1 formations.',
        'description_it': '5 difensori con ali alte. Contro 4-2N-1-2W-1.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['5 defenders', 'High AML/AMR', 'Counter ready', 'Solid base'],
        'strengths_it': ['5 difensori', 'AML/AMR alti', 'Pronto al contropiede', 'Base solida'],
        'weaknesses_en': ['Lone striker', 'Limited creativity', 'AML/AMR must track back'],
        'weaknesses_it': ['Attaccante solitario', 'Creatività limitata', 'AML/AMR devono rientrare'],
        'tactic_type_en': 'Defensive / Wide Counter',
        'tactic_type_it': 'Difensivo / Contropiede Largo',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': '5 at back tight. Long balls to AML/AMR then to ST.',
                'tip_it': '5 in difesa stretti. Palle lunghe ad AML/AMR poi a ST.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact. Use AML/AMR pace on counters.',
                'tip_it': 'Resta compatto. Usa la velocità di AML/AMR in contropiede.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Push AML/AMR very high. Create for lone striker.',
                'tip_it': "Spingi AML/AMR molto in alto. Crea per l'attaccante solitario.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['4-3-3', '4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '4131w1',
        'name': '4-1-3-1W-1',
        'description_en': 'Skewed winger formation. AMR (or AML) on same side as ST. Against 3-4-1-2 (defensive weakness).',
        'description_it': 'Ala skewata stesso lato del ST. Contro 3-4-1-2 (debolezza difensiva).',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'DMC', 'MC', 'MC', 'MC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Skewed attack', 'Overload one side', 'Creative midfield', 'Exploits weak flanks'],
        'strengths_it': [
            'Attacco skewato',
            'Sovraccarica un lato',
            'Centrocampo creativo',
            'Sfrutta fianchi deboli'
        ],
        'weaknesses_en': ['Unbalanced', 'Needs quality AMR', 'Exposed on opposite flank'],
        'weaknesses_it': ['Sbilanciata', 'Richiede AMR di qualità', 'Esposta sul fianco opposto'],
        'tactic_type_en': 'Attacking / Skewed',
        'tactic_type_it': 'Attaccante / Skewata',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Right Flank',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Right Flank',
                'focus_passing_it': 'Fascia destra',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Counter through skewed side. AMR + ST combo on breaks.',
                'tip_it': 'Contropiede dal lato skewato. Combo AMR + ST nelle ripartenze.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Right Flank',
                'focus_passing_it': 'Fascia destra',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Overload right side. AMR and ST create overload.',
                'tip_it': 'Sovraccarica il lato destro. AMR e ST creano superiorità.',
                'arrows': {
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Right Flank',
                'focus_passing_it': 'Fascia destra',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'All-out attack on right side! 2nd half switch to high pressing.',
                'tip_it': 'Attacco totale sul lato destro! Nel 2°T passa a pressing alto.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-3-1-1', '4-1-4-1'],
        'effective_against': []
    },
    {
        'id': '3n52v',
        'name': '3N-5-2 V',
        'description_en': '3 DCs + 5 midfielders with high AML/AMR. Effective against parked bus formations.',
        'description_it': '3 DC + 5 MF con ali alte. Efficace contro bus parcheggiato.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['High wingers', 'Midfield control', 'Two strikers', 'Breaks parked bus'],
        'strengths_it': ['Ali alte', 'Controllo centrocampo', 'Due attaccanti', 'Sfonda il catenaccio'],
        'weaknesses_en': ['3 CBs exposed', 'No full-backs', 'High stamina needed'],
        'weaknesses_it': ['3 DC esposti', 'Nessun terzino', 'Richiede alta resistenza'],
        'tactic_type_en': 'Attacking / Anti-Parked Bus',
        'tactic_type_it': 'Attaccante / Anti-Catenaccio',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': True,
                'tip_en': 'Protect 3 CBs. Use AML/AMR pace on counters to strikers.',
                'tip_it': 'Proteggi i 3 DC. Usa la velocità di AML/AMR in contropiede verso gli attaccanti.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Use width to stretch parked buses. AML/AMR + 2 STs overload.',
                'tip_it': "Usa l'ampiezza per allargare il catenaccio. AML/AMR + 2 ST sovraccaricano.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'All-out attack! 7 players forward will destroy them!',
                'tip_it': 'Attacco totale! 7 giocatori in avanti li distruggeranno!',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3-2-2-2-1 B (Butterfly)', '4-3N-2W-1'],
        'effective_against': ['4-1-2-1-2 ND (Narrow Diamond)', '5-1-1-1-2']
    },
    {
        'id': '43n2w1',
        'name': '4-3N-2W-1',
        'description_en': '3 central MCs + high AML/AMR. Very common at high levels.',
        'description_it': '3 MC + AML/AMR alti. Molto diffusa ai livelli alti.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Central control', 'High wingers', 'Popular at high levels', 'Flexible'],
        'strengths_it': ['Controllo centrale', 'Ali alte', 'Popolare ai livelli alti', 'Flessibile'],
        'weaknesses_en': ['Lone striker', 'Needs quality MCs', 'Can be exposed on counters'],
        'weaknesses_it': ['Attaccante solitario', 'Richiede MC di qualità', 'Può essere esposta ai contropiedi'],
        'tactic_type_en': 'Attacking / High Level Meta',
        'tactic_type_it': 'Attaccante / Meta Alto Livello',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Normal',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': True,
                'tip_en': '3 MCs control center. AML/AMR break on counters to ST.',
                'tip_it': '3 MC controllano il centro. AML/AMR sfondano in contropiede verso ST.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Dominate midfield with 3 MCs. AML/AMR create for lone ST.',
                'tip_it': 'Domina il centrocampo con 3 MC. AML/AMR creano per ST solitario.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'All-out attack! Push all 6 attackers forward!',
                'tip_it': 'Attacco totale! Spingi tutti i 6 attaccanti in avanti!',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-1-4-1-1'],
        'effective_against': ['3-5-2 F (Flat)', '3N-2-2-2-1 B (Butterfly 3N)', '3N-5-2 V', '5-4-1 F (Flat)']
    },
    {
        'id': '3151amc',
        'name': '3-1-5-1 AMC',
        'description_en': 'Highly tactical formation with DMC shield and 5-man midfield including AMC as playmaker. 3 variants: A (Central Dominance), B (Balanced Control), C (Quick Transition). Very effective with a quality AMC.',
        'description_it': 'Formazione altamente tattica con DMC scudo e centrocampo a 5 con AMC come regista. 3 varianti: A (Dominio Centrale), B (Bilanciata-Controllo), C (Transizione Rapida). Molto efficace con un AMC di qualità.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MC', 'MC', 'MR', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            '5-man midfield dominance',
            'AMC as creative hub',
            '3 tactical variants',
            'Flexible against any formation'
        ],
        'strengths_it': [
            'Dominio centrocampo a 5',
            'AMC come perno creativo',
            '3 varianti tattiche',
            'Flessibile contro ogni formazione'
        ],
        'weaknesses_en': ['Requires quality AMC (135+)', 'Only 3 defenders', 'Wings can be exposed'],
        'weaknesses_it': ['Richiede AMC di qualità (135+)', 'Solo 3 difensori', 'Fasce possono essere esposte'],
        'tactic_type_en': 'META 2025 / Multi-Variant',
        'tactic_type_it': 'META 2025 / Multi-Variante',
        'arrows': '★ Variante A: MC↑ | Variante C: MR↓ ML↓',
        'variants': {
            'A': {
                'name_en': 'Central Dominance',
                'name_it': 'Dominio Centrale',
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'passing_focus': 'Through the Middle',
                'passing_focus_it': 'Per il Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'pressing': 'High',
                'pressing_it': 'Alto',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'counter_attack': False,
                'arrows': {
                    'MC': '↑'
                },
                'best_against': ['4-4-2', '4-1-4-1', '4-3-1-2', '3-5-2'],
                'tip_en': 'Ideal with top AMC (135+). Crush weaker opponents. AMC is the creative hub.',
                'tip_it': 'Ideale con AMC top (135+). Schiaccia avversari più deboli. AMC è il perno creativo.'
            },
            'B': {
                'name_en': 'Balanced Control',
                'name_it': 'Bilanciata-Controllo',
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'passing_focus': 'Mixed',
                'passing_focus_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misto',
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': True,
                'counter_attack': True,
                'arrows': {},
                'best_against': ['3-4-3', '4-2-3-1', '4-5-1'],
                'tip_en': 'For balanced matches. Safer at the back, AMC and ST have freedom.',
                'tip_it': 'Per partite equilibrate. Più sicura dietro, AMC e ST con libertà.'
            },
            'C': {
                'name_en': 'Quick Transition',
                'name_it': 'Transizione Rapida',
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'passing_focus': 'Mixed',
                'passing_focus_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': True,
                'counter_attack': True,
                'arrows': {
                    'MR': '↓',
                    'ML': '↓'
                },
                'best_against': ['4-3-3', '5-3-2', '4-2-2-2'],
                'tip_en': 'Perfect vs high-possession teams. Use AMC-ST-MR-ML speed on counters.',
                'tip_it': 'Perfetta vs squadre con alto possesso. Usa velocità AMC-ST-MR-ML nei contropiedi.'
            }
        },
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Man-to-Man',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'variant': 'C',
                'tip_en': 'Use Variant C (Quick Transition). Stay compact, counter with AMC-ST speed. MR/ML with backward arrows.',
                'tip_it': 'Usa Variante C (Transizione Rapida). Resta compatto, contropiede con velocità AMC-ST. MR/ML con frecce indietro.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': True,
                'variant': 'B',
                'tip_en': 'Use Variant B (Balanced). Safer at the back, AMC and ST have freedom to create.',
                'tip_it': 'Usa Variante B (Bilanciata). Più sicura dietro, AMC e ST con libertà di creare.',
                'arrows': {
                    'DMC': '↓',
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'variant': 'A',
                'tip_en': 'Use Variant A (Central Dominance). Crush them! High press, AMC as creative hub, MC forward arrows.',
                'tip_it': 'Usa Variante A (Dominio Centrale). Schiaccialo! Pressing alto, AMC come perno, MC con frecce avanti.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-2-3-1', '4-3-3'],
        'effective_against': []
    },
    {
        'id': '31411',
        'name': '3-1-4-1-1',
        'description_en': 'The most popular META formation in 2026. 3 DCs with DMC shield, 4 midfielders, AMC as second striker. DMC arrow down, AMC arrow up for maximum effectiveness.',
        'description_it': 'La formazione META più popolare nel 2026. 3 DC con scudo DMC, 4 centrocampisti, AMC come secondo attaccante. Freccia DMC giù, freccia AMC su per massima efficacia.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Solid 3-man defense + DMC shield',
            'AMC acts as second striker',
            'Wide coverage with ML/MR',
            'Great counter-attacking',
            'Beats 12%+ stronger opponents'
        ],
        'strengths_it': [
            'Difesa solida a 3 + scudo DMC',
            'AMC agisce da secondo attaccante',
            'Copertura ampia con ML/MR',
            'Ottimo contropiede',
            'Batte avversari 12%+ più forti'
        ],
        'weaknesses_en': ['Vulnerable to 3-striker formations', 'Wings can be exposed', 'Requires quality DMC'],
        'weaknesses_it': [
            'Vulnerabile a formazioni con 3 attaccanti',
            'Fasce possono essere esposte',
            'Richiede DMC di qualità'
        ],
        'tactic_type_en': '★ META 2026 / Counter-Attack',
        'tactic_type_it': '★ META 2026 / Contropiede',
        'arrows': 'DMC↓ AMC↑',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Easy',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Sulle Fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': "Stay compact! DMC↓ to protect DCs. Counter through flanks. Don't chase the ball, let them come.",
                'tip_it': 'Resta compatto! DMC↓ per proteggere i DC. Contropiede sulle fasce. Non rincorrere, lascia che vengano.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': True,
                'tip_en': 'Balance attack and defense. AMC↑ for extra goal threat. Use ML/MR for width.',
                'tip_it': 'Equilibra attacco e difesa. AMC↑ per minaccia extra. Usa ML/MR per ampiezza.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Dominate! Push everyone forward. AMC↑ MC↑ for 3-man attack. High press to suffocate.',
                'tip_it': 'Domina! Spingi tutti avanti. AMC↑ MC↑ per attacco a 3. Pressing alto per soffocare.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-1-2-1-2 ND (Narrow Diamond)', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': ['4-3N-2W-1']
    },
    {
        'id': '41221',
        'name': '4-1-2-2-1',
        'description_en': 'Super defensive formation with 5 virtual defenders. DL-DC-DC-DR-DMC creates a wall. 2 MC + 2 wingers for balance. Great for parking the bus.',
        'description_it': 'Formazione super difensiva con 5 difensori virtuali. DL-DC-DC-DR-DMC crea un muro. 2 MC + 2 ali per equilibrio. Ottima per parcheggiare il bus.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Ultra Defensive',
        'category_it': 'Ultra Difensiva',
        'strengths_en': [
            '5-man virtual defense',
            'Almost impossible to break',
            'Hard tackling effective',
            'Zonal marking dominant',
            'Best for weaker teams'
        ],
        'strengths_it': [
            'Difesa virtuale a 5',
            'Quasi impossibile da sfondare',
            'Contrasti duri efficaci',
            'Marcatura a zona dominante',
            'Migliore per squadre deboli'
        ],
        'weaknesses_en': ['Very limited attack', 'Relies on counters only', 'Can be boring to play'],
        'weaknesses_it': ['Attacco molto limitato', 'Si basa solo sui contropiedi', 'Può essere noiosa da giocare'],
        'tactic_type_en': 'META 2026 / Ultra Defensive',
        'tactic_type_it': 'META 2026 / Ultra Difensiva',
        'arrows': 'DMC↓ MC↓',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Hard',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Ultra Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Sulle Fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': 'PARK THE BUS! Everyone defends. Only AML/AMR and ST go forward on counters. Pray for 0-0.',
                'tip_it': 'PARCHEGGIA IL BUS! Tutti difendono. Solo AML/AMR e ST avanti in contropiede. Prega per lo 0-0.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Sulle Fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': 'Stay solid. Let them have the ball. Strike fast on counter with AML/AMR pace.',
                'tip_it': 'Resta solido. Lascia che abbiano palla. Colpisci veloce in contropiede con velocità AML/AMR.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': True,
                'tip_en': 'Push MC forward slightly. Still counter-focused but more possession.',
                'tip_it': 'Spingi MC leggermente avanti. Ancora focus contropiede ma più possesso.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-2-2-2 H (Hexagon)'],
        'effective_against': []
    },
    {
        'id': 'fn9w',
        'name': 'False Nine + Wingers',
        'description_en': 'NEW META attacking system. AMC plays as False Nine dropping deep, ML/MR push to AML/AMR as inverted wingers. Only 3 attackers but devastating effectiveness.',
        'description_it': 'NUOVO sistema META offensivo. AMC gioca come Falso Nove arretrando, ML/MR spingono a AML/AMR come ali invertite. Solo 3 attaccanti ma efficacia devastante.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'AMR', 'AMC'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': [
            'False Nine pulls defenders out',
            'Wingers exploit space',
            'Can switch formation live',
            'No subs needed to attack',
            'Confuses opponent'
        ],
        'strengths_it': [
            'Falso Nove attira difensori',
            'Ali sfruttano spazi',
            'Può cambiare formazione live',
            'Non servono sostituzioni per attaccare',
            "Confonde l'avversario"
        ],
        'weaknesses_en': ['Requires very specific players', 'No true striker', 'Complex to master'],
        'weaknesses_it': [
            'Richiede giocatori molto specifici',
            'Nessun vero attaccante',
            'Complessa da padroneggiare'
        ],
        'tactic_type_en': '★ NEW META 2026 / False Nine',
        'tactic_type_it': '★ NUOVO META 2026 / Falso Nove',
        'arrows': 'AMC↓ (as False Nine) AML↑ AMR↑',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Normal',
                'pressing_it': 'Normale',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': "False Nine drops, AML/AMR run into space. Quick 1-2s in the middle. Don't force it.",
                'tip_it': 'Falso Nove arretra, AML/AMR corrono negli spazi. Rapidi 1-2 al centro. Non forzare.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'A Zona',
                'offside_trap': False,
                'tip_en': 'Full False Nine system. AMC drops, AML/AMR attack. Confuse their defense!',
                'tip_it': 'Sistema Falso Nove completo. AMC arretra, AML/AMR attaccano. Confondi la loro difesa!',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Push False Nine to ST, wingers to AML/AMR. Full attack mode! 3 attackers vs their weak defense.',
                'tip_it': 'Spingi Falso Nove a ST, ali a AML/AMR. Modalità attacco totale! 3 attaccanti vs loro difesa debole.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-1-3-1-1', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '424',
        'name': '4-2-4',
        'description_en': '4-2-4 - Attacking formation. Maximum aggression; four fixed attackers.',
        'description_it': '4-2-4 - formazione attaccante. Massima aggressività; 4 attaccanti fissi.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'AML', 'ST', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Maximum aggression', 'Four fixed attackers', 'High goal output'],
        'strengths_it': ['Massima aggressività', '4 attaccanti fissi', 'Alta produzione di gol'],
        'weaknesses_en': ['No real midfield', 'Very exposed defense'],
        'weaknesses_it': ['Centrocampo assente', 'Difesa molto esposta'],
        'tactic_type_en': 'All-Out Attack',
        'tactic_type_it': 'Attacco Totale',
        'recommended_tactics': {
            'mentality': 'Hard Attacking',
            'focus_passing': 'Mixed',
            'passing_style': 'Long',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Hard',
            'marking': 'Man-to-Man',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-2-4, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-2-4, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Ultra-attacking shape for desperate comebacks, but leaves the defense completely open.',
                'tip_it': 'Modulo ultra-offensivo per rimonte disperate, ma lascia la difesa totalmente scoperta.',
                'arrows': {
                    'ST': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-2-4, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-2-4, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '41311',
        'name': '4-1-3-1-1',
        'description_en': '4-1-3-1-1 - Balanced formation. Defensive solidity; frequent clean sheets.',
        'description_it': '4-1-3-1-1 - formazione bilanciata. Solidità difensiva; clean sheet frequenti.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'MC', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Defensive solidity', 'Frequent clean sheets', 'Neutralizes the 4-3-3'],
        'strengths_it': ['Solidità difensiva', 'Clean sheet frequenti', 'Neutralizza il 4-3-3'],
        'weaknesses_en': ['Narrow-margin wins', 'Limited attack'],
        'weaknesses_it': ['Vittorie di misura', 'Attacco limitato'],
        'tactic_type_en': 'Balanced / Clean Sheet',
        'tactic_type_it': 'Bilanciato / Porta Inviolata',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Mixed',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-1-3-1-1, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-1-3-1-1, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Excellent for protecting the result and shutting down the opponent's wide attacks.",
                'tip_it': 'Eccellente per proteggere il risultato e annullare gli attacchi esterni avversari.',
                'arrows': {
                    'DMC': '↓',
                    'MC': '↓',
                    'AMC': '↓',
                    'ST': '↓'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-1-3-1-1, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-1-3-1-1, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'MC': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-5-1 V-Style'],
        'effective_against': ['3-1-2-1-3', '4-1-3-1W-1', 'False Nine + Wingers']
    },
    {
        'id': '4321xt',
        'name': '4-3-2-1 XT (Xmas Tree)',
        'description_en': '4-3-2-1 XT (Xmas Tree) - Defensive formation. Powerful midfield; flank protection.',
        'description_it': '4-3-2-1 XT (Xmas Tree) - formazione difensiva. Centrocampo potente; protezione dei fianchi.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Powerful midfield', 'Flank protection', 'Midfield density'],
        'strengths_it': ['Centrocampo potente', 'Protezione dei fianchi', 'Densità mediana'],
        'weaknesses_en': ['Isolated strikers', 'Lacks width'],
        'weaknesses_it': ['Punte isolate', 'Manca di ampiezza'],
        'tactic_type_en': 'Defensive / Midfield Control',
        'tactic_type_it': 'Difensivo / Controllo Centrocampo',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-3-2-1 XT (Xmas Tree), drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-3-2-1 XT (Xmas Tree), abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Ideal to exploit the flanks and keep a solid midfield against versatile formations.',
                'tip_it': 'Ideale per sfruttare le fasce e mantenere un centrocampo solido contro formazioni versatili.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-3-2-1 XT (Xmas Tree), raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-3-2-1 XT (Xmas Tree), alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-5-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '532',
        'name': '5-3-2',
        'description_en': '5-3-2 - Defensive formation. Prevents goals; central density.',
        'description_it': '5-3-2 - formazione difensiva. Previene i gol; densità centrale.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'ST', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Prevents goals', 'Central density', 'Defensive stability'],
        'strengths_it': ['Previene i gol', 'Densità centrale', 'Stabilità difensiva'],
        'weaknesses_en': ['Few scoring chances', 'Low defensive line'],
        'weaknesses_it': ['Poche occasioni da gol', 'Baricentro basso'],
        'tactic_type_en': 'Ultra Defensive / Bus Parking',
        'tactic_type_it': 'Ultra Difensivo / Catenaccio',
        'recommended_tactics': {
            'mentality': 'Hard Defending',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 5-3-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 5-3-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "The best choice to 'park the bus' and defend a lead you've earned.",
                'tip_it': "La scelta migliore per 'parcheggiare l'autobus' e difendere un vantaggio acquisito.",
                'arrows': {
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 5-3-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 5-3-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['4-3-3', '4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '413n2',
        'name': '4-1-3N-2',
        'description_en': '4-1-3N-2 - Balanced formation. Beats the 4-2-3-1; balance between the lines.',
        'description_it': '4-1-3N-2 - formazione bilanciata. Batte il 4-2-3-1; equilibrio tra le linee.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'MC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Beats the 4-2-3-1', 'Balance between the lines', 'Central density'],
        'strengths_it': ['Batte il 4-2-3-1', 'Equilibrio tra le linee', 'Densità centrale'],
        'weaknesses_en': ['Struggles against wide play', 'Requires quality MCs'],
        'weaknesses_it': ['Soffre il gioco laterale', 'Richiede MC di qualità'],
        'tactic_type_en': 'Balanced / Central Counter',
        'tactic_type_it': 'Bilanciato / Contropiede Centrale',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-1-3N-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-1-3N-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Great for dominating central possession and striking on the counter through the middle.',
                'tip_it': 'Ottima per dominare il possesso centrale e colpire in contropiede attraverso il centro.',
                'arrows': {
                    'MC': '↑',
                    'DMC': '↓',
                    'DL': '↓',
                    'DC': '↓',
                    'DR': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-1-3N-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-1-3N-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1'],
        'effective_against': ['4-2-3-1 Attack']
    },
    {
        'id': '3412',
        'name': '3-4-1-2',
        'description_en': '3-4-1-2 - Attacking formation. Central presence; dominates the final third.',
        'description_it': '3-4-1-2 - formazione attaccante. Presenza centrale; domina la trequarti.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Central presence', 'Dominates the final third', 'Numerical superiority'],
        'strengths_it': ['Presenza centrale', 'Domina la trequarti', 'Superiorità numerica'],
        'weaknesses_en': ['Weak wide defense', 'Vulnerable on the flanks'],
        'weaknesses_it': ['Difesa laterale debole', 'Vulnerabile sulle fasce'],
        'tactic_type_en': 'Attacking / Central',
        'tactic_type_it': 'Attaccante / Centrale',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Man-to-Man',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3-4-1-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3-4-1-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Effective at breaking through centrally, but needs disciplined full-backs to cover the wide spaces.',
                'tip_it': 'Efficace per sfondare centralmente, ma richiede terzini bloccati per coprire le praterie esterne.',
                'arrows': {
                    'ST': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3-4-1-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3-4-1-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3-5-2 F (Flat)', '4-1-2-1-2 ND (Narrow Diamond)'],
        'effective_against': ['3-2-2-2-1 B (Butterfly)', '4-3N-3']
    },
    {
        'id': '31312',
        'name': '3-1-3-1-2',
        'description_en': '3-1-3-1-2 - Attacking formation. Many shooting chances; attacking orientation.',
        'description_it': '3-1-3-1-2 - formazione attaccante. Molte opportunità di tiro; orientamento offensivo.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Many shooting chances', 'Attacking orientation', 'Flexibility'],
        'strengths_it': ['Molte opportunità di tiro', 'Orientamento offensivo', 'Flessibilità'],
        'weaknesses_en': ['Exposed to counters', 'Risky back three'],
        'weaknesses_it': ['Esposta ai contropiedi', 'Difesa a tre rischiosa'],
        'tactic_type_en': 'Attacking / High Press',
        'tactic_type_it': 'Attaccante / Pressing Alto',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3-1-3-1-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3-1-3-1-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'A basic attacking shape to create constant scoring chances against static defenses.',
                'tip_it': "Modulo d'attacco basilare per creare costanti occasioni da gol contro difese statiche.",
                'arrows': {
                    'ST': '↑',
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3-1-3-1-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3-1-3-1-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3-5-2 F (Flat)', '3-5-2 V (V-Style)', '4-5-1 V-Style'],
        'effective_against': []
    },
    {
        'id': '43n3',
        'name': '4-3N-3',
        'description_en': '4-3N-3 - Balanced formation. Counters the 4-5-1 V-Style; attacking density.',
        'description_it': '4-3N-3 - formazione bilanciata. Counter del 4-5-1 V-Style; densità offensiva.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'ST', 'AMR'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Counters the 4-5-1 V-Style', 'Attacking density', 'Central pressing'],
        'strengths_it': ['Counter del 4-5-1 V-Style', 'Densità offensiva', 'Pressing centrale'],
        'weaknesses_en': ['Lacks width', 'Vulnerable if they stretch the play'],
        'weaknesses_it': ['Manca di ampiezza', 'Vulnerabile se allargano il gioco'],
        'tactic_type_en': 'Balanced / Anti V-Style',
        'tactic_type_it': 'Bilanciato / Anti V-Style',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Mixed',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-3N-3, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-3N-3, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Aggressive variant ideal to unlock crowded midfields and dominate the central zone.',
                'tip_it': 'Variante aggressiva ideale per scardinare centrocampi folti e dominare la zona centrale.',
                'arrows': {
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-3N-3, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-3N-3, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-1-2', '3-4-3', '4-1-4-1'],
        'effective_against': ['4-5-1 V-Style']
    },
    {
        'id': '3132w1',
        'name': '3-1-3-2W-1',
        'description_en': '3-1-3-2W-1 - Attacking formation. Wide attack with AML/AMR; solid dmc anchor.',
        'description_it': '3-1-3-2W-1 - formazione attaccante. Attacco largo con AML/AMR; solido dmc ancora.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Wide attack with AML/AMR', 'Solid DMC anchor', 'Central spine compact'],
        'strengths_it': ['Attacco largo con AML/AMR', 'Solido DMC ancora', 'Spina dorsale compatta'],
        'weaknesses_en': ['Three CBs exposed', 'Single striker isolated'],
        'weaknesses_it': ['3 DC esposti', 'Punta solitaria isolata'],
        'tactic_type_en': 'Attacking / Wide',
        'tactic_type_it': 'Attaccante / Largo',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3-1-3-2W-1, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3-1-3-2W-1, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Used to win easily through the flanks when the opponent defends poorly out wide.',
                'tip_it': "Si usa per vincere facilmente sulle fasce quando l'avversario difende male lateralmente.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3-1-3-2W-1, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3-1-3-2W-1, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-1-4-1', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '3n1213',
        'name': '3N-1-2-1-3',
        'description_en': '3N-1-2-1-3 - Attacking formation. Three-striker firepower; creative amc.',
        'description_it': '3N-1-2-1-3 - formazione attaccante. Potenza dei tre attaccanti; amc creativo.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'AMC', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Three-striker firepower', 'Creative AMC', 'High pressing'],
        'strengths_it': ['Potenza dei tre attaccanti', 'AMC creativo', 'Pressing alto'],
        'weaknesses_en': ['Only 3 CBs and 2 MCs', 'Vulnerable to fast counters'],
        'weaknesses_it': ['Solo 3 DC e 2 MC', 'Vulnerabile a contropiedi veloci'],
        'tactic_type_en': 'Hard Attacking / Triple Strike',
        'tactic_type_it': 'Molto Attaccante / Tripletta',
        'recommended_tactics': {
            'mentality': 'Hard Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Hard',
            'marking': 'Man-to-Man',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3N-1-2-1-3, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3N-1-2-1-3, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Uses an overwhelming three-striker attack to break down static four-back defenses.',
                'tip_it': 'Sfrutta un attacco pesantissimo a tre punte per scardinare difese a quattro statiche.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3N-1-2-1-3, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3N-1-2-1-3, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '4213',
        'name': '4-2-1-3',
        'description_en': '4-2-1-3 - Attacking formation. AMC and full attack; two mcs cover.',
        'description_it': '4-2-1-3 - formazione attaccante. AMC e attacco completo; due mc coprono.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'AMC', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['AMC and full attack', 'Two MCs cover', 'Strong central creativity'],
        'strengths_it': ['AMC e attacco completo', 'Due MC coprono', 'Forte creatività centrale'],
        'weaknesses_en': ['Needs technical MCs', 'Risks gaps behind AMC'],
        'weaknesses_it': ['Richiede MC tecnici', "Rischia varchi dietro l'AMC"],
        'tactic_type_en': 'Attacking / Modern',
        'tactic_type_it': 'Attaccante / Moderno',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-2-1-3, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-2-1-3, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Maximizes attacking output through simultaneous use of wingers and a central AMC.',
                'tip_it': "Massimizza la produzione offensiva con l'uso simultaneo di ali e un trequartista centrale.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-2-1-3, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-2-1-3, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '4112n2',
        'name': '4-1-1-2N-2',
        'description_en': '4-1-1-2N-2 - Balanced formation. Two creative AMCs; compact central control.',
        'description_it': '4-1-1-2N-2 - formazione bilanciata. Due AMC creativi; controllo centrale compatto.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'AMC', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Two creative AMCs', 'Compact central control', 'Two strikers up front'],
        'strengths_it': ['Due AMC creativi', 'Controllo centrale compatto', 'Due punte in attacco'],
        'weaknesses_en': ['No natural wingers', 'Heavily central'],
        'weaknesses_it': ['Nessuna ala naturale', 'Molto centrale'],
        'tactic_type_en': 'Balanced / Double AMC',
        'tactic_type_it': 'Bilanciato / Doppio AMC',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-1-1-2N-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-1-1-2N-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Excellent at controlling play between opponent's lines thanks to the two central #10s.",
                'tip_it': 'Ottima per controllare il gioco tra le linee avversarie grazie ai due trequartisti centrali.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-1-1-2N-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-1-1-2N-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1'],
        'effective_against': []
    },
    {
        'id': '3w13n12',
        'name': '3W-1-3N-1-2',
        'description_en': '3W-1-3N-1-2 - Balanced formation. Asymmetric flexibility; amc bridge.',
        'description_it': '3W-1-3N-1-2 - formazione bilanciata. Flessibilità asimmetrica; amc raccordo.',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'MC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Asymmetric flexibility', 'AMC bridge', 'Wide back three'],
        'strengths_it': ['Flessibilità asimmetrica', 'AMC raccordo', 'Difesa a tre larga'],
        'weaknesses_en': ['Hard to balance', 'Requires versatile players'],
        'weaknesses_it': ['Difficile da bilanciare', 'Richiede giocatori versatili'],
        'tactic_type_en': 'Balanced / Asymmetric',
        'tactic_type_it': 'Bilanciato / Asimmetrico',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Mixed',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3W-1-3N-1-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3W-1-3N-1-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Asymmetric variant useful for balancing a back three with a supporting AMC.',
                'tip_it': 'Variante asimmetrica utile per bilanciare una difesa a tre con un trequartista di supporto.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3W-1-3N-1-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3W-1-3N-1-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3-4-3', '3-5-2 V (V-Style)', '4-1-4-1'],
        'effective_against': []
    },
    {
        'id': '3313',
        'name': '3-3-1-3',
        'description_en': '3-3-1-3 - Attacking formation. Maximum width and creativity; amc orchestrates.',
        'description_it': '3-3-1-3 - formazione attaccante. Massima ampiezza e creatività; amc orchestratore.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'MC', 'MC', 'MC', 'AMC', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Maximum width and creativity', 'AMC orchestrates', 'Three forwards'],
        'strengths_it': ['Massima ampiezza e creatività', 'AMC orchestratore', 'Tre attaccanti'],
        'weaknesses_en': ['Only 3 CBs', 'Massive risk on counters'],
        'weaknesses_it': ['Solo 3 DC', 'Rischio enorme nei contropiedi'],
        'tactic_type_en': 'Hard Attacking / Possession',
        'tactic_type_it': 'Molto Attaccante / Possesso',
        'recommended_tactics': {
            'mentality': 'Hard Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Hard',
            'marking': 'Man-to-Man',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3-3-1-3, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3-3-1-3, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Ultra-creative module to dominate possession all over the opponent's half.",
                'tip_it': 'Modulo ultra-creativo per dominare il possesso in tutta la metà campo avversaria.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3-3-1-3, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3-3-1-3, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-1-4-1', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '42n12n1',
        'name': '4-2N-1-2N-1',
        'description_en': '4-2N-1-2N-1 - Balanced formation. Double DMC shield; double amc creators.',
        'description_it': '4-2N-1-2N-1 - formazione bilanciata. Doppio scudo DMC; doppio amc creativi.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'DMC', 'MC', 'AMC', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Double DMC shield', 'Double AMC creators', 'Maximum central density'],
        'strengths_it': ['Doppio scudo DMC', 'Doppio AMC creativi', 'Massima densità centrale'],
        'weaknesses_en': ['No wide play', 'One isolated striker'],
        'weaknesses_it': ['Niente gioco largo', 'Punta isolata'],
        'tactic_type_en': 'Balanced / Central Density',
        'tactic_type_it': 'Bilanciato / Densità Centrale',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-2N-1-2N-1, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-2N-1-2N-1, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Provides incredible central density using two DMs and two AMCs.',
                'tip_it': "Fornisce un'incredibile densità centrale con due mediani e due trequartisti.",
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-2N-1-2N-1, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-2N-1-2N-1, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1'],
        'effective_against': []
    },
    {
        'id': '51112',
        'name': '5-1-1-1-2',
        'description_en': '5-1-1-1-2 - Defensive formation. Narrow pyramid shape; amc linkup.',
        'description_it': '5-1-1-1-2 - formazione difensiva. Piramide stretta; amc raccordo.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'DMC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Narrow pyramid shape', 'AMC linkup', 'Two strikers for counter'],
        'strengths_it': ['Piramide stretta', 'AMC raccordo', 'Due punte da contropiede'],
        'weaknesses_en': ['No wide players', 'Static if AMC marked'],
        'weaknesses_it': ['Nessun esterno', "Statica se l'AMC è marcato"],
        'tactic_type_en': 'Defensive / Pyramid',
        'tactic_type_it': 'Difensivo / Piramide',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 5-1-1-1-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 5-1-1-1-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Tight pyramid module: closes all gaps and breaks quickly through the AMC.',
                'tip_it': "Modulo a piramide stretto: chiude i varchi e riparte velocemente con l'AMC.",
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 5-1-1-1-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 5-1-1-1-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['3N-5-2 V', '4-3-3', '4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '52w2n1',
        'name': '5-2W-2N-1',
        'description_en': '5-2W-2N-1 - Defensive formation. Maximum flank coverage; five at back.',
        'description_it': '5-2W-2N-1 - formazione difensiva. Massima copertura laterale; cinque dietro.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'ML', 'MR', 'AMC', 'AMC', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Maximum flank coverage', 'Five at back', 'Solid midfield'],
        'strengths_it': ['Massima copertura laterale', 'Cinque dietro', 'Centrocampo solido'],
        'weaknesses_en': ['Lone striker isolated', 'Limited attacking output'],
        'weaknesses_it': ['Punta isolata', 'Produzione offensiva limitata'],
        'tactic_type_en': 'Defensive / Wide Coverage',
        'tactic_type_it': 'Difensivo / Copertura Larga',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 5-2W-2N-1, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 5-2W-2N-1, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Guarantees maximum lateral coverage combining five defenders and wide midfielders.',
                'tip_it': 'Garantisce la massima copertura laterale combinando cinque difensori e centrocampisti di fascia.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 5-2W-2N-1, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 5-2W-2N-1, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['4-3-3', '4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '42211',
        'name': '4-2-2-1-1',
        'description_en': '4-2-2-1-1 - Defensive formation. Double DMC shield; quad midfield.',
        'description_it': '4-2-2-1-1 - formazione difensiva. Doppio scudo DMC; centrocampo a quattro.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'DMC', 'MC', 'MC', 'AMC', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Double DMC shield', 'Quad midfield', 'AMC creator'],
        'strengths_it': ['Doppio scudo DMC', 'Centrocampo a quattro', 'AMC creatore'],
        'weaknesses_en': ['Lone striker', 'Low attacking output'],
        'weaknesses_it': ['Attaccante solitario', 'Bassa produzione offensiva'],
        'tactic_type_en': 'Defensive / Double Shield',
        'tactic_type_it': 'Difensivo / Doppio Scudo',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Mixed',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-2-2-1-1, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-2-2-1-1, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Creates a double screen in front of defense to neutralize strong #10s and forwards.',
                'tip_it': 'Crea un doppio schermo davanti alla difesa per annullare trequartisti e punte forti.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-2-2-1-1, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-2-2-1-1, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-3-3', '4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '41131',
        'name': '4-1-1-3-1',
        'description_en': '4-1-1-3-1 - Attacking formation. Five attacking players; dmc anchor.',
        'description_it': "4-1-1-3-1 - formazione attaccante. Cinque giocatori d'attacco; dmc ancora.",
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Five attacking players', 'DMC anchor', 'Maximum creative density'],
        'strengths_it': ["Cinque giocatori d'attacco", 'DMC ancora', 'Massima densità creativa'],
        'weaknesses_en': ['Only DMC defends', 'Vulnerable to counters', 'Needs technical AMCs'],
        'weaknesses_it': ['Solo il DMC difende', 'Vulnerabile ai contropiedi', 'Richiede AMC tecnici'],
        'tactic_type_en': 'Attacking / Trequarti dense',
        'tactic_type_it': 'Attaccante / Trequarti densa',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-1-1-3-1, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-1-1-3-1, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Modern attacking shape: DMC alone protects, while the AMC and wingers flood the final third.',
                'tip_it': 'Modulo moderno offensivo: il DMC protegge da solo mentre AMC e ali affollano la trequarti.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-1-1-3-1, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-1-1-3-1, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-3-3', '4-5-1 V-Style', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '4312',
        'name': '4-3-1-2',
        'description_en': '4-3-1-2 - Balanced formation. Diamond midfield; amc creator.',
        'description_it': '4-3-1-2 - formazione bilanciata. Rombo centrale; amc creatore.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Diamond midfield', 'AMC creator', 'Two strikers', 'Strong central control'],
        'strengths_it': ['Rombo centrale', 'AMC creatore', 'Due punte', 'Forte controllo centrale'],
        'weaknesses_en': ['No natural wingers', 'Vulnerable on flanks'],
        'weaknesses_it': ['Nessuna ala naturale', 'Vulnerabile sulle fasce'],
        'tactic_type_en': 'Balanced / Narrow Diamond Wide',
        'tactic_type_it': 'Bilanciato / Rombo Largo',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-3-1-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-3-1-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Wide diamond, focused on central possession. Use the AMC to feed both strikers.',
                'tip_it': "Diamante largo focalizzato sul possesso centrale. Usa l'AMC per servire le due punte.",
                'arrows': {
                    'ST': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-3-1-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-3-1-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-5-1 V-Style'],
        'effective_against': []
    },
    {
        'id': '31213',
        'name': '3-1-2-1-3',
        'description_en': '3-1-2-1-3 - Attacking formation. Three forwards; creative amc.',
        'description_it': '3-1-2-1-3 - formazione attaccante. Tre attaccanti; amc creativo.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'AMC', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Three forwards', 'Creative AMC', 'DMC shield', 'Strong central density'],
        'strengths_it': ['Tre attaccanti', 'AMC creativo', 'Schermo DMC', 'Forte densità centrale'],
        'weaknesses_en': ['Only 3 CBs', 'DMC alone in defensive midfield'],
        'weaknesses_it': ['Solo 3 DC', 'DMC solo davanti alla difesa'],
        'tactic_type_en': 'Hard Attacking / Modern',
        'tactic_type_it': 'Molto Attaccante / Moderno',
        'recommended_tactics': {
            'mentality': 'Hard Attacking',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Hard',
            'marking': 'Man-to-Man',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3-1-2-1-3, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3-1-2-1-3, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Aggressive shape with three forwards and a creative AMC. Risky but lethal in attack.',
                'tip_it': 'Modulo aggressivo con tre punte e un AMC creativo. Rischioso ma letale in attacco.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3-1-2-1-3, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3-1-2-1-3, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-1-3-1-1', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '3421',
        'name': '3-4-2-1',
        'description_en': '3-4-2-1 - Balanced formation. Double AMC creators; wing-back width.',
        'description_it': '3-4-2-1 - formazione bilanciata. Doppio AMC creativo; ampiezza degli esterni.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MR', 'AML', 'AMR', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Double AMC creators', 'Wing-back width', 'Three-CB stability', 'Italian variant'],
        'strengths_it': ['Doppio AMC creativo', 'Ampiezza degli esterni', 'Stabilità a 3 DC', 'Variante italiana'],
        'weaknesses_en': ['Vulnerable to fast wings', 'Needs mobile wing-backs'],
        'weaknesses_it': ['Vulnerabile contro ali veloci', 'Richiede esterni mobili'],
        'tactic_type_en': 'Balanced / Conte-Style',
        'tactic_type_it': 'Bilanciato / Stile Conte',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Mixed',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3-4-2-1, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3-4-2-1, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Conte/Tuchel style with double #10 behind a lone striker. Wing-backs provide width.',
                'tip_it': 'Stile Conte/Tuchel con doppio trequartista dietro la punta. Gli esterni danno ampiezza.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3-4-2-1, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3-4-2-1, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-3-3'],
        'effective_against': []
    },
    {
        'id': '523',
        'name': '5-2-3',
        'description_en': '5-2-3 - Defensive formation. Five at back; two wide forwards.',
        'description_it': '5-2-3 - formazione difensiva. Cinque dietro; due ali avanzate.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'MC', 'MC', 'AML', 'ST', 'AMR'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Five at back', 'Two wide forwards', 'Counter-attack outlets', 'Solid central defense'],
        'strengths_it': ['Cinque dietro', 'Due ali avanzate', 'Sbocchi per contropiede', 'Difesa centrale solida'],
        'weaknesses_en': ['Only 2 MCs', 'Lone striker isolated'],
        'weaknesses_it': ['Solo 2 MC', 'Attaccante centrale isolato'],
        'tactic_type_en': 'Defensive / Counter with Width',
        'tactic_type_it': 'Difensivo / Contropiede con Ampiezza',
        'recommended_tactics': {
            'mentality': 'Defensive',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Long',
            'counter_attack': True,
            'pressing': 'Low',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Hard Defending',
                'mentality_it': 'Molto Difensivo',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 5-2-3, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 5-2-3, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Five at back with wide forwards for fast counters. Strong against attacking opponents.',
                'tip_it': 'Cinque dietro con ali avanti per contropiedi veloci. Forte contro avversari offensivi.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 5-2-3, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 5-2-3, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 5,
        'vulnerable_to': ['4-3-3', '4-4-2 C (Classic)'],
        'effective_against': []
    },
    {
        'id': '222n22',
        'name': '4-2-2-2 N (Narrow)',
        'description_en': '4-2-2-2 N (Narrow) - Balanced formation. Double DMC shield; compact midfield.',
        'description_it': '4-2-2-2 N (Narrow) - formazione bilanciata. Doppio scudo DMC; centrocampo compatto.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'DMC', 'MC', 'MC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Double DMC shield', 'Compact midfield', 'Two strikers', 'Strong central spine'],
        'strengths_it': ['Doppio scudo DMC', 'Centrocampo compatto', 'Due punte', 'Forte spina dorsale centrale'],
        'weaknesses_en': ['No wide attack', 'Predictable through middle'],
        'weaknesses_it': ['Niente attacco largo', 'Prevedibile al centro'],
        'tactic_type_en': 'Balanced / Compact Hexagon Variant',
        'tactic_type_it': 'Bilanciato / Variante Compatta',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-2-2-2 N (Narrow), drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-2-2-2 N (Narrow), abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Narrow variant of 4-2-2-2 Hexagon. Even more central focus, less width.',
                'tip_it': 'Variante stretta del 4-2-2-2 Hexagon. Ancora più focus centrale, meno ampiezza.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-2-2-2 N (Narrow), raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-2-2-2 N (Narrow), alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-3-3'],
        'effective_against': []
    },
    {
        'id': '3142w',
        'name': '3-1-4-2 W',
        'description_en': '3-1-4-2 W - Attacking formation. DMC anchor; wide midfield.',
        'description_it': '3-1-4-2 W - formazione attaccante. DMC ancora; centrocampo largo.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['DMC anchor', 'Wide midfield', 'Two strikers', 'Strong wing presence'],
        'strengths_it': ['DMC ancora', 'Centrocampo largo', 'Due punte', 'Forte presenza laterale'],
        'weaknesses_en': ['Only 3 CBs', 'Wide MCs must defend too'],
        'weaknesses_it': ['Solo 3 DC', 'I MC larghi devono difendere'],
        'tactic_type_en': 'Attacking / Wide',
        'tactic_type_it': 'Attaccante / Largo',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 3-1-4-2 W, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 3-1-4-2 W, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Wide version of 3-1-4-2: ML/MR provide width while two strikers attack centrally.',
                'tip_it': 'Versione larga del 3-1-4-2: ML/MR danno ampiezza, le due punte attaccano al centro.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 3-1-4-2 W, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 3-1-4-2 W, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 3,
        'vulnerable_to': ['4-2-3-1', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '4231a',
        'name': '4-2-3-1 Attack',
        'description_en': '4-2-3-1 Attack - Attacking formation. Versatile shape; amc creator.',
        'description_it': '4-2-3-1 Attack - formazione attaccante. Modulo versatile; amc creatore.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Attaccante',
        'strengths_en': ['Versatile shape', 'AMC creator', 'Wide attackers', 'High pressing potential'],
        'strengths_it': ['Modulo versatile', 'AMC creatore', 'Ali offensive', 'Alto potenziale di pressing'],
        'weaknesses_en': ['Lone striker', 'Two MCs only'],
        'weaknesses_it': ['Punta solitaria', 'Solo due MC'],
        'tactic_type_en': 'Attacking / Modern Press',
        'tactic_type_it': 'Attaccante / Pressing Moderno',
        'recommended_tactics': {
            'mentality': 'Attacking',
            'focus_passing': 'Mixed',
            'passing_style': 'Short',
            'counter_attack': False,
            'pressing': 'High',
            'tackling': 'Normal',
            'marking': 'Man-to-Man',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-2-3-1 Attack, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-2-3-1 Attack, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Modern 4-2-3-1 with high pressing setup. Used by top European teams.',
                'tip_it': '4-2-3-1 moderno con setup pressing alto. Usato dai top club europei.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Hard Attacking',
                'mentality_it': 'Molto Attaccante',
                'focus_passing': 'Mixed',
                'focus_passing_it': 'Misto',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-2-3-1 Attack, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-2-3-1 Attack, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑',
                    'ST': '↑'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['4-1-3N-2', '4-3-3', '5-4-1 F (Flat)'],
        'effective_against': []
    },
    {
        'id': '42312',
        'name': '4-2-3-1-2',
        'description_en': '4-2-3-1-2 - Balanced formation. Double DMC shield; central amc.',
        'description_it': '4-2-3-1-2 - formazione bilanciata. Doppio scudo DMC; amc centrale.',
        'positions': ['GK', 'DR', 'DC', 'DC', 'DL', 'DMC', 'DMC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Double DMC shield', 'Central AMC', 'Two strikers', 'Strong central control'],
        'strengths_it': ['Doppio scudo DMC', 'AMC centrale', 'Due punte', 'Forte controllo centrale'],
        'weaknesses_en': ['Heavy central focus', 'Needs creative MC'],
        'weaknesses_it': ['Molto centrale', 'Richiede MC creativo'],
        'tactic_type_en': 'Balanced / Hybrid',
        'tactic_type_it': 'Bilanciato / Ibrido',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Against stronger sides, stay compact in the 4-2-3-1-2, drop the pressing and hit on the counter.',
                'tip_it': 'Contro avversari più forti, resta compatto col 4-2-3-1-2, abbassa il pressing e riparti in contropiede.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓',
                    'DMC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Hybrid modern shape: double DMC for stability + AMC for creativity + two strikers.',
                'tip_it': 'Ibrido moderno: doppio DMC per stabilità + AMC creativo + due punte.',
                'arrows': {
                    'DMC': '↓'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Per il centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': False,
                'tip_en': 'Against weaker sides, push high with the 4-2-3-1-2, raise pressing and man-marking to dominate.',
                'tip_it': 'Contro avversari più deboli, spingi alto col 4-2-3-1-2, alza pressing e marcatura a uomo per dominare.',
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ST': '↑',
                    'DMC': '↓'
                }
            }
        },
        'defense_count': 4,
        'vulnerable_to': ['3-4-3', '4-1-4-1', '4-3-3'],
        'effective_against': []
    },
    {
        'id': '313n2w1',
        'name': '3-1-3N-2W-1',
        'description_en': '3-1-3N-2W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3-1-3N-2W-1 con difesa a 3. Eccelle nello sfruttare le fasce contro difese a tre.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence'],
        'strengths_it': [
            'Eccelle nello sfruttare le fasce contro difese a tre.',
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa'
        ],
        'weaknesses_en': [
            'Defensive flanks exposed to counters',
            'Lacks width: vulnerable to opposition wingers',
            'Isolated striker without support'
        ],
        'weaknesses_it': [
            'I 3 DC centrali esposti a imbucate rapide se i laterali non rientrano.',
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': [
            '3N-3(DMC/MC)-2W-2',
            '3N-4-1-2',
            '3W-5-1-1',
            '3W-5-2 F',
            '4-1-3N-2',
            '4-2-1-3',
            '4-3N-1-2'
        ],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3n142',
        'name': '3N-1-4-2',
        'description_en': '3N-1-4-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-1-4-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'DMC shielding the defence',
            'Possession control in midfield',
            'Strike partnership'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Controllo del possesso in mediana',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3W-2DMC-3W-1-1 ML (Maple Leaf)', '4-3W-1-2', '5-2-1-2 X (X-Style)'],
        'vulnerable_to': ['3-5-1-1 V', '4-5-1 V-Style'],
        'defense_count': 3
    },
    {
        'id': '313n12',
        'name': '3-1-3N-1-2',
        'description_en': '3-1-3N-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3-1-3N-1-2 con difesa a 3. Forza il possesso centrale e sovraccarica la trequarti avversaria.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence', 'Strike partnership'],
        'strengths_it': [
            'Forza il possesso centrale e sovraccarica la trequarti avversaria.',
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fianchi scoperti ai lanci lunghi per le ali.',
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'MC': '↑'
                }
            }
        },
        'effective_against': ['3N-1-2-1-3', '3N-5-1-1', '3W-4-1-2', '3W-5-2 V'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3n412',
        'name': '3N-4-1-2',
        'description_en': '3N-4-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-4-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-2-2-2 H (Hexagon)', '5-3N-2', '5-3W-2'],
        'vulnerable_to': ['3-1-3N-2W-1', '4-1-2-1-2 ND (Narrow Diamond)', '3N-2W-2N-1-2'],
        'defense_count': 3
    },
    {
        'id': '413w11',
        'name': '4-1-3W-1-1',
        'description_en': '4-1-3W-1-1 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1-3W-1-1 con difesa a 4. DMC a protezione della difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['DMC shielding the defence', 'Good width'],
        'strengths_it': ['DMC a protezione della difesa', 'Buona ampiezza di gioco'],
        'weaknesses_en': [],
        'weaknesses_it': [],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3-4-1-2', '4-3N-2N-1'],
        'vulnerable_to': ['3-1-4-1-1', '4-4-1-1', '5-1DMC-2-2'],
        'defense_count': 4
    },
    {
        'id': '4132',
        'name': '4-1-3-2',
        'description_en': '4-1-3-2 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1-3-2 con difesa a 4. Ottimo equilibrio tra mediana e attacco a due punte.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'MC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['DMC shielding the defence', 'Strike partnership'],
        'strengths_it': [
            'Ottimo equilibrio tra mediana e attacco a due punte.',
            'DMC a protezione della difesa',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Puo soffrire la mancanza di ampiezza contro ali molto larghe.',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': ['4-3-3', '5-1-2N-1-1', '5-1-2W-1-1'],
        'vulnerable_to': [],
        'defense_count': 4
    },
    {
        'id': '3511v',
        'name': '3-5-1-1 V',
        'description_en': '3-5-1-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3-5-1-1 con difesa a 3. Densita centrale insuperabile per annullare moduli stretti.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Midfield numerical advantage', 'Possession control in midfield'],
        'strengths_it': [
            'Densita centrale insuperabile per annullare moduli stretti.',
            'Superiorita numerica a centrocampo',
            'Controllo del possesso in mediana'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            "Poca spinta offensiva laterale se l'AMC rimane isolato.",
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3N-1-3W-1-2 D (Dandelion)', '3N-1-3W-2N-1', '3N-1-4-2', '4-3W-3'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3n2w2n12',
        'name': '3N-2W-2N-1-2',
        'description_en': '3N-2W-2N-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-2W-2N-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MR', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Double screen in front of defence', 'Strike partnership'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'MC': '↑'
                }
            }
        },
        'effective_against': ['3N-4-1-2', '3N-5-1-1', '3W-4-1-2', '3W-5-1-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '4411',
        'name': '4-4-1-1',
        'description_en': '4-4-1-1 shape with a back 4. Good width',
        'description_it': 'Modulo 4-4-1-1 con difesa a 4. Buona ampiezza di gioco',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Good width'],
        'strengths_it': ['Buona ampiezza di gioco'],
        'weaknesses_en': [],
        'weaknesses_it': [],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-1-3W-1-1', '4-3N-2W-1'],
        'vulnerable_to': ['3-5-2 F (Flat)', '4-5-1 V-Style'],
        'defense_count': 4
    },
    {
        'id': '3n52f',
        'name': '3N-5-2 F',
        'description_en': '3N-5-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-5-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Midfield numerical advantage', 'Possession control in midfield', 'Strike partnership'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Controllo del possesso in mediana',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3W-1-3W-1-2'],
        'vulnerable_to': ['3-1-4-2', '4-3N-2W-1', '4-2-3-1'],
        'defense_count': 3
    },
    {
        'id': '313w12',
        'name': '3-1-3W-1-2',
        'description_en': '3-1-3W-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3-1-3W-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'DMC a protezione della difesa', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3N-2N-1-2W-2', '4-2-3W-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '53w2',
        'name': '5-3W-2',
        'description_en': '5-3W-2 shape with a back 5. Very solid back five',
        'description_it': 'Modulo 5-3W-2 con difesa a 5. Difesa solidissima a 5',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'ML', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Very solid back five', 'Good width', 'Strike partnership'],
        'strengths_it': ['Difesa solidissima a 5', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': ['Limited attacking push unless wingers advance'],
        'weaknesses_it': ['Poca spinta offensiva se le ali non salgono'],
        'tactic_type_en': 'Defensive',
        'tactic_type_it': 'Difensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3-1-4-2', '4-2-3W-1'],
        'vulnerable_to': ['3N-5-2 V', '3N-4-1-2', '4-4-2 C (Classic)'],
        'defense_count': 5
    },
    {
        'id': '3n13w12',
        'name': '3N-1-3W-1-2',
        'description_en': '3N-1-3W-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-1-3W-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'DMC a protezione della difesa', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['5-2-2N-1', '5-2W-2N-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3n2w3n2',
        'name': '3N-2W-3N-2',
        'description_en': '3N-2W-3N-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-2W-3N-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MR', 'AMC', 'AMC', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3W-2N-2N-2W-1', '5-2-2W-1'],
        'vulnerable_to': ['3-5-2 F (Flat)', '4-5-1 F (Flat)', '5-4-1 F (Flat)'],
        'defense_count': 3
    },
    {
        'id': '3n1411',
        'name': '3N-1-4-1-1',
        'description_en': '3N-1-4-1-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-1-4-1-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'DMC shielding the defence',
            'Possession control in midfield'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Controllo del possesso in mediana'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-2N-1-2N-1'],
        'vulnerable_to': ['3-1-4-1-1', '4-1-2-1-2 ND (Narrow Diamond)', '4-5-1 V-Style'],
        'defense_count': 3
    },
    {
        'id': '413w2',
        'name': '4-1-3W-2',
        'description_en': '4-1-3W-2 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1-3W-2 con difesa a 4. DMC a protezione della difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['DMC shielding the defence', 'Good width', 'Strike partnership'],
        'strengths_it': ['DMC a protezione della difesa', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': [],
        'weaknesses_it': [],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-1-2(AMC)-3'],
        'vulnerable_to': ['3-1-4-2', '4-5-1 V-Style', '5-4-1 F (Flat)'],
        'defense_count': 4
    },
    {
        'id': '43w12',
        'name': '4-3W-1-2',
        'description_en': '4-3W-1-2 shape with a back 4. Good width',
        'description_it': 'Modulo 4-3W-1-2 con difesa a 4. Buona ampiezza di gioco',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'ML', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Good width', 'Strike partnership'],
        'strengths_it': ['Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': [],
        'weaknesses_it': [],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-1-2-1-2 WD (Wide Diamond)'],
        'vulnerable_to': ['3N-1-4-2', '4-1-4-1', '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'],
        'defense_count': 4
    },
    {
        'id': '3w52f',
        'name': '3W-5-2 F',
        'description_en': '3W-5-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-5-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'ML', 'MC', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'Possession control in midfield',
            'Good width',
            'Strike partnership'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3W-2N-3W-2'],
        'vulnerable_to': ['3-1-3N-2W-1', '4-5-1 V-Style'],
        'defense_count': 3
    },
    {
        'id': '3w123w1',
        'name': '3W-1-2-3W-1',
        'description_en': '3W-1-2-3W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-1-2-3W-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence', 'Good width'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['5-2-2(AML-AMR)-1', '5-2-2W-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3w1411',
        'name': '3W-1-4-1-1',
        'description_en': '3W-1-4-1-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-1-4-1-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'DMC shielding the defence',
            'Possession control in midfield',
            'Good width'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-2N-1-2W-1'],
        'vulnerable_to': ['3-5-2 V (V-Style)', '4-5-1 V-Style'],
        'defense_count': 3
    },
    {
        'id': '3w52v',
        'name': '3W-5-2 V',
        'description_en': '3W-5-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-5-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'ML', 'MC', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'Possession control in midfield',
            'Good width',
            'Strike partnership'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['3W-2N-2W-1-2'],
        'vulnerable_to': ['3-1-3N-1-2', '4-2-2-2 H (Hexagon)', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3n2n12w2',
        'name': '3N-2N-1-2W-2',
        'description_en': '3N-2N-1-2W-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-2N-1-2W-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'MC', 'AML', 'AMR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Double screen in front of defence', 'Strike partnership'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['4-1-1-2W-2'],
        'vulnerable_to': ['3-1-3W-1-2', '4-4-2 C (Classic)', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3n43',
        'name': '3N-4-3',
        'description_en': '3N-4-3 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-4-3 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MR', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-2-2-2 H (Hexagon)'],
        'vulnerable_to': ['3-5-2 F (Flat)', '4-4-2 C (Classic)', '5-4-1 F (Flat)'],
        'defense_count': 3
    },
    {
        'id': '3w2n3w2',
        'name': '3W-2N-3W-2',
        'description_en': '3W-2N-3W-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-2N-3W-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['4-2-3N(AMC)-1'],
        'vulnerable_to': ['3W-5-2 F', '4-4-2 C (Classic)', '5-4-1 F (Flat)'],
        'defense_count': 3
    },
    {
        'id': '513w1',
        'name': '5-1-3W-1',
        'description_en': '5-1-3W-1 shape with a back 5. Very solid back five',
        'description_it': 'Modulo 5-1-3W-1 con difesa a 5. Difesa solidissima a 5',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MR', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Very solid back five', 'DMC shielding the defence', 'Good width'],
        'strengths_it': ['Difesa solidissima a 5', 'DMC a protezione della difesa', 'Buona ampiezza di gioco'],
        'weaknesses_en': ['Limited attacking push unless wingers advance', 'Isolated striker without support'],
        'weaknesses_it': ['Poca spinta offensiva se le ali non salgono', 'Punta isolata senza rifinitore'],
        'tactic_type_en': 'Defensive',
        'tactic_type_it': 'Difensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': ['4-1-2(AMC)-3'],
        'vulnerable_to': ['3N-5-2 V', '4-5-1 F (Flat)', '3N-2W-3W-2'],
        'defense_count': 5
    },
    {
        'id': '3n2w2n2w1',
        'name': '3N-2W-2N-2W-1',
        'description_en': '3N-2W-2N-2W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-2W-2N-2W-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MR', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Double screen in front of defence'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Doppio schermo davanti alla difesa'],
        'weaknesses_en': [
            'Defensive flanks exposed to counters',
            'Lacks width: vulnerable to opposition wingers',
            'Isolated striker without support'
        ],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie',
            'Punta isolata senza rifinitore'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['5-1-2N-1-1', '5-1-2W-1-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3w2n13w1',
        'name': '3W-2N-1-3W-1',
        'description_en': '3W-2N-1-3W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-2N-1-3W-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'DMC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Double screen in front of defence', 'Good width'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['4-1-1-2N-2'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3w43',
        'name': '3W-4-3',
        'description_en': '3W-4-3 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-4-3 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'ML', 'MC', 'MC', 'MR', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-5-2 V (V-Style)', '4-2-2-2 H (Hexagon)', '4-5-1 V-Style'],
        'defense_count': 3
    },
    {
        'id': '412n12',
        'name': '4-1-2N-1-2',
        'description_en': '4-1-2N-1-2 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1-2N-1-2 con difesa a 4. DMC a protezione della difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['DMC shielding the defence', 'Strike partnership'],
        'strengths_it': ['DMC a protezione della difesa', "Coppia d'attacco"],
        'weaknesses_en': ['Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': ['Manca ampiezza: vulnerabile alle ali avversarie'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': ['5-2-1-2 X (X-Style)'],
        'vulnerable_to': [],
        'defense_count': 4
    },
    {
        'id': '33n3w1',
        'name': '3-3N-3W-1',
        'description_en': '3-3N-3W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3-3N-3W-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'MC', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage'],
        'strengths_it': ['Superiorita numerica a centrocampo'],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['3W-1-5-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3w142',
        'name': '3W-1-4-2',
        'description_en': '3W-1-4-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-1-4-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'DMC shielding the defence',
            'Possession control in midfield',
            'Good width'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-4-1-2', '4-1-2-1-2 ND (Narrow Diamond)'],
        'defense_count': 3
    },
    {
        'id': '313n3',
        'name': '3-1-3N-3',
        'description_en': '3-1-3N-3 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3-1-3N-3 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'MC', 'AML', 'ST', 'AMR'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'DMC a protezione della difesa', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'MC': '↑'
                }
            }
        },
        'effective_against': ['3N-5-2 V'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3n13w12ddandelion',
        'name': '3N-1-3W-1-2 D (Dandelion)',
        'description_en': '3N-1-3W-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-1-3W-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'DMC a protezione della difesa', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-5-1-1 V', '4-4-2 C (Classic)', '4-5-1 V-Style'],
        'defense_count': 3
    },
    {
        'id': '413n11',
        'name': '4-1-3N-1-1',
        'description_en': '4-1-3N-1-1 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1-3N-1-1 con difesa a 4. DMC a protezione della difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'MC', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['DMC shielding the defence'],
        'strengths_it': ['DMC a protezione della difesa'],
        'weaknesses_en': ['Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': ['Manca ampiezza: vulnerabile alle ali avversarie'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-4-2', '3-1-4-1-1', '4-5-1 V-Style'],
        'defense_count': 4
    },
    {
        'id': '3n511',
        'name': '3N-5-1-1',
        'description_en': '3N-5-1-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-5-1-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Midfield numerical advantage', 'Possession control in midfield'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Controllo del possesso in mediana'],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-3N-1-2', '4-1-2-1-2 ND (Narrow Diamond)', '3N-2W-2N-1-2'],
        'defense_count': 3
    },
    {
        'id': '3w511',
        'name': '3W-5-1-1',
        'description_en': '3W-5-1-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-5-1-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'ML', 'MC', 'MC', 'MC', 'MR', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Midfield numerical advantage', 'Possession control in midfield', 'Good width'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-3N-2W-1', '4-1-2-1-2 ND (Narrow Diamond)', '3N-2W-2N-1-2'],
        'defense_count': 3
    },
    {
        'id': '3n2dmcmc3w2',
        'name': '3N-2(DMC/MC)-3W-2',
        'description_en': '3N-2(DMC/MC)-3W-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-2(DMC/MC)-3W-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'ML', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'Double screen in front of defence',
            'Possession control in midfield',
            'Strike partnership'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            'Controllo del possesso in mediana',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-4-2', '4-1-2-1-2 ND (Narrow Diamond)', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3w2dmcmc3w2',
        'name': '3W-2(DMC/MC)-3W-2',
        'description_en': '3W-2(DMC/MC)-3W-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-2(DMC/MC)-3W-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'DMC', 'ML', 'MC', 'MR', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'Double screen in front of defence',
            'Possession control in midfield',
            'Good width'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-4-2', '4-4-2 C (Classic)', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3n3dmcmc2w2',
        'name': '3N-3(DMC/MC)-2W-2',
        'description_en': '3N-3(DMC/MC)-2W-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-3(DMC/MC)-2W-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'DMC', 'DMC', 'ML', 'MR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Double screen in front of defence', 'Strike partnership'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-3N-2W-1', '4-3N-2W-1', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3w2n2w12',
        'name': '3W-2N-2W-1-2',
        'description_en': '3W-2N-2W-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-2N-2W-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'DMC', 'ML', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': [
            'Midfield numerical advantage',
            'Double screen in front of defence',
            'Good width',
            'Strike partnership'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            'Buona ampiezza di gioco',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3W-5-2 V', '4-5-1 V-Style', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3w2n2n2w1',
        'name': '3W-2N-2N-2W-1',
        'description_en': '3W-2N-2N-2W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-2N-2N-2W-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'DMC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Double screen in front of defence', 'Good width'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Isolated striker without support'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi', 'Punta isolata senza rifinitore'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-4-1-2', '4-4-2 C (Classic)', '3N-2W-3N-2'],
        'defense_count': 3
    },
    {
        'id': '3w151',
        'name': '3W-1-5-1',
        'description_en': '3W-1-5-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-1-5-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MC', 'MC', 'MR', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [
            'Midfield numerical advantage',
            'DMC shielding the defence',
            'Possession control in midfield',
            'Good width'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Isolated striker without support'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi', 'Punta isolata senza rifinitore'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-3N-3W-1', '4-3N-2W-1', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3w13w2n1',
        'name': '3W-1-3W-2N-1',
        'description_en': '3W-1-3W-2N-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-1-3W-2N-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'AMC', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence', 'Good width'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-5-2 V (V-Style)', '4-5-1 V-Style', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3n13w2n1',
        'name': '3N-1-3W-2N-1',
        'description_en': '3N-1-3W-2N-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-1-3W-2N-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'AMC', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'DMC a protezione della difesa'],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-5-1-1 V', '4-5-1 V-Style', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 3
    },
    {
        'id': '3w13w12',
        'name': '3W-1-3W-1-2',
        'description_en': '3W-1-3W-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-1-3W-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'DMC', 'ML', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': [
            'Midfield numerical advantage',
            'DMC shielding the defence',
            'Good width',
            'Strike partnership'
        ],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa',
            'Buona ampiezza di gioco',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3N-5-2 F', '4-4-2 C (Classic)', '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'],
        'defense_count': 3
    },
    {
        'id': '3w412',
        'name': '3W-4-1-2',
        'description_en': '3W-4-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-4-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'ML', 'MC', 'MC', 'MR', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-3N-1-2', '4-1-2-1-2 ND (Narrow Diamond)', '3N-2W-2N-1-2'],
        'defense_count': 3
    },
    {
        'id': '41dmc23',
        'name': '4-1(DMC)-2-3',
        'description_en': '4-1(DMC)-2-3 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1(DMC)-2-3 con difesa a 4. DMC a protezione della difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AML', 'ST', 'AMR'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['DMC shielding the defence', 'Strike partnership'],
        'strengths_it': ['DMC a protezione della difesa', "Coppia d'attacco"],
        'weaknesses_en': ['Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': ['Manca ampiezza: vulnerabile alle ali avversarie'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-4-2', '4-1-4-1', '5-3N-2'],
        'defense_count': 4
    },
    {
        'id': '4112w2',
        'name': '4-1-1-2W-2',
        'description_en': '4-1-1-2W-2 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1-1-2W-2 con difesa a 4. DMC a protezione della difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'AML', 'AMR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['DMC shielding the defence', 'Good width', 'Strike partnership'],
        'strengths_it': ['DMC a protezione della difesa', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': [],
        'weaknesses_it': [],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3N-2N-1-2W-2', '4-2-3-1', '3N-3W-2-2'],
        'defense_count': 4
    },
    {
        'id': '3n3w22',
        'name': '3N-3W-2-2',
        'description_en': '3N-3W-2-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-3W-2-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MR', 'AML', 'AMR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['4-1-1-2W-2'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '42n12w1',
        'name': '4-2N-1-2W-1',
        'description_en': '4-2N-1-2W-1 shape with a back 4. Double screen in front of defence',
        'description_it': 'Modulo 4-2N-1-2W-1 con difesa a 4. Doppio schermo davanti alla difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'DMC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Double screen in front of defence', 'Good width'],
        'strengths_it': ['Doppio schermo davanti alla difesa', 'Buona ampiezza di gioco'],
        'weaknesses_en': ['Isolated striker without support'],
        'weaknesses_it': ['Punta isolata senza rifinitore'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3W-1-4-1-1', '4-4-2 C (Classic)', '5-2-2(AML-AMR)-1'],
        'defense_count': 4
    },
    {
        'id': '43w3',
        'name': '4-3W-3',
        'description_en': '4-3W-3 shape with a back 4. Good width',
        'description_it': 'Modulo 4-3W-3 con difesa a 4. Buona ampiezza di gioco',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'ML', 'MC', 'MR', 'AML', 'ST', 'AMR'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Good width', 'Strike partnership'],
        'strengths_it': ['Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': [],
        'weaknesses_it': [],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-5-1-1 V', '4-5-1 V-Style', '5-4-1 F (Flat)'],
        'defense_count': 4
    },
    {
        'id': '42dmc3w1',
        'name': '4-2(DMC)-3W-1',
        'description_en': '4-2(DMC)-3W-1 shape with a back 4. Double screen in front of defence',
        'description_it': 'Modulo 4-2(DMC)-3W-1 con difesa a 4. Doppio schermo davanti alla difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'DMC', 'ML', 'MC', 'MR', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Double screen in front of defence', 'Possession control in midfield', 'Good width'],
        'strengths_it': [
            'Doppio schermo davanti alla difesa',
            'Controllo del possesso in mediana',
            'Buona ampiezza di gioco'
        ],
        'weaknesses_en': ['Isolated striker without support'],
        'weaknesses_it': ['Punta isolata senza rifinitore'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-3-2W-1', '4-1-4-1', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 4
    },
    {
        'id': '423w1',
        'name': '4-2-3W-1',
        'description_en': '4-2-3W-1 shape with a back 4. Good width',
        'description_it': 'Modulo 4-2-3W-1 con difesa a 4. Buona ampiezza di gioco',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Good width'],
        'strengths_it': ['Buona ampiezza di gioco'],
        'weaknesses_en': [],
        'weaknesses_it': [],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-3W-1-2', '4-4-2 C (Classic)', '5-3W-2'],
        'defense_count': 4
    },
    {
        'id': '43n12',
        'name': '4-3N-1-2',
        'description_en': '4-3N-1-2 shape with a back 4. Strike partnership',
        'description_it': "Modulo 4-3N-1-2 con difesa a 4. Coppia d'attacco",
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['Strike partnership'],
        'strengths_it': ["Coppia d'attacco"],
        'weaknesses_en': ['Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': ['Manca ampiezza: vulnerabile alle ali avversarie'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-3N-2W-1', '4-5-1 V-Style', '3-2-2-2-1 B (Butterfly)'],
        'defense_count': 4
    },
    {
        'id': '43n2n1',
        'name': '4-3N-2N-1',
        'description_en': '4-3N-2N-1 shape with a back 4. ',
        'description_it': 'Modulo 4-3N-2N-1 con difesa a 4. ',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'MC', 'AMC', 'AMC', 'ST'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': [],
        'strengths_it': [],
        'weaknesses_en': ['Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': ['Manca ampiezza: vulnerabile alle ali avversarie'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-4-1-1', '4-1-3W-1-1', '3W-2DMC-3W-1-1 ML (Maple Leaf)'],
        'defense_count': 4
    },
    {
        'id': '412amc3',
        'name': '4-1-2(AMC)-3',
        'description_en': '4-1-2(AMC)-3 shape with a back 4. DMC shielding the defence',
        'description_it': 'Modulo 4-1-2(AMC)-3 con difesa a 4. DMC a protezione della difesa',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AML', 'ST', 'AMR'],
        'category_en': 'Balanced',
        'category_it': 'Bilanciata',
        'strengths_en': ['DMC shielding the defence', 'Strike partnership'],
        'strengths_it': ['DMC a protezione della difesa', "Coppia d'attacco"],
        'weaknesses_en': ['Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': ['Manca ampiezza: vulnerabile alle ali avversarie'],
        'tactic_type_en': 'Balanced',
        'tactic_type_it': 'Bilanciata',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-4-2', '4-1-3W-2', '5-1-3W-1'],
        'defense_count': 4
    },
    {
        'id': '513n1',
        'name': '5-1-3N-1',
        'description_en': '5-1-3N-1 shape with a back 5. Very solid back five',
        'description_it': 'Modulo 5-1-3N-1 con difesa a 5. Difesa solidissima a 5',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'MC', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Very solid back five', 'DMC shielding the defence'],
        'strengths_it': ['Difesa solidissima a 5', 'DMC a protezione della difesa'],
        'weaknesses_en': [
            'Limited attacking push unless wingers advance',
            'Lacks width: vulnerable to opposition wingers',
            'Isolated striker without support'
        ],
        'weaknesses_it': [
            'Poca spinta offensiva se le ali non salgono',
            'Manca ampiezza: vulnerabile alle ali avversarie',
            'Punta isolata senza rifinitore'
        ],
        'tactic_type_en': 'Defensive',
        'tactic_type_it': 'Difensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3N-5-2 V', '4-1-3-1-1', '3N-3W-3W-1'],
        'defense_count': 5
    },
    {
        'id': '3n3w3w1',
        'name': '3N-3W-3W-1',
        'description_en': '3N-3W-3W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-3W-3W-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MC', 'MR', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco'],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['5-1-3N-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3n2w3w2',
        'name': '3N-2W-3W-2',
        'description_en': '3N-2W-3W-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-2W-3W-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MR', 'AML', 'AMC', 'AMR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'ML': '↑',
                    'MR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['5-1-3W-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '512n11',
        'name': '5-1-2N-1-1',
        'description_en': '5-1-2N-1-1 shape with a back 5. Very solid back five',
        'description_it': 'Modulo 5-1-2N-1-1 con difesa a 5. Difesa solidissima a 5',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'DMC', 'MC', 'MC', 'AMC', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Very solid back five', 'DMC shielding the defence'],
        'strengths_it': ['Difesa solidissima a 5', 'DMC a protezione della difesa'],
        'weaknesses_en': [
            'Limited attacking push unless wingers advance',
            'Lacks width: vulnerable to opposition wingers'
        ],
        'weaknesses_it': [
            'Poca spinta offensiva se le ali non salgono',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Defensive',
        'tactic_type_it': 'Difensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3N-5-2 V', '4-1-3-2', '3N-2W-2N-2W-1'],
        'defense_count': 5
    },
    {
        'id': '512w11',
        'name': '5-1-2W-1-1',
        'description_en': '5-1-2W-1-1 shape with a back 5. Very solid back five',
        'description_it': 'Modulo 5-1-2W-1-1 con difesa a 5. Difesa solidissima a 5',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'DMC', 'ML', 'MR', 'AMC', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Very solid back five', 'DMC shielding the defence', 'Good width'],
        'strengths_it': ['Difesa solidissima a 5', 'DMC a protezione della difesa', 'Buona ampiezza di gioco'],
        'weaknesses_en': ['Limited attacking push unless wingers advance'],
        'weaknesses_it': ['Poca spinta offensiva se le ali non salgono'],
        'tactic_type_en': 'Defensive',
        'tactic_type_it': 'Difensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'ML': '↑',
                    'MR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'ML': '↑',
                    'MR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3N-5-2 V', '4-1-3-2', '3N-2W-2N-2W-1'],
        'defense_count': 5
    },
    {
        'id': '522w1',
        'name': '5-2-2W-1',
        'description_en': '5-2-2W-1 shape with a back 5. Very solid back five',
        'description_it': 'Modulo 5-2-2W-1 con difesa a 5. Difesa solidissima a 5',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Very solid back five', 'Good width'],
        'strengths_it': ['Difesa solidissima a 5', 'Buona ampiezza di gioco'],
        'weaknesses_en': ['Limited attacking push unless wingers advance', 'Isolated striker without support'],
        'weaknesses_it': ['Poca spinta offensiva se le ali non salgono', 'Punta isolata senza rifinitore'],
        'tactic_type_en': 'Defensive',
        'tactic_type_it': 'Difensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3W-1-2-3W-1', '4-4-2 C (Classic)', '3N-2W-3N-2'],
        'defense_count': 5
    },
    {
        'id': '522n1',
        'name': '5-2-2N-1',
        'description_en': '5-2-2N-1 shape with a back 5. Very solid back five',
        'description_it': 'Modulo 5-2-2N-1 con difesa a 5. Difesa solidissima a 5',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DC', 'DR', 'MC', 'MC', 'AMC', 'AMC', 'ST'],
        'category_en': 'Defensive',
        'category_it': 'Difensiva',
        'strengths_en': ['Very solid back five'],
        'strengths_it': ['Difesa solidissima a 5'],
        'weaknesses_en': [
            'Limited attacking push unless wingers advance',
            'Lacks width: vulnerable to opposition wingers'
        ],
        'weaknesses_it': [
            'Poca spinta offensiva se le ali non salgono',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Defensive',
        'tactic_type_it': 'Difensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3N-1-3W-1-2', '4-2-2-1-1', '3W-2-3W-2'],
        'defense_count': 5
    },
    {
        'id': '3w23w2',
        'name': '3W-2-3W-2',
        'description_en': '3W-2-3W-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-2-3W-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['5-2-2N-1'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '3n2w212',
        'name': '3N-2W-2-1-2',
        'description_en': '3N-2W-2-1-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3N-2W-2-1-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DC', 'DC', 'DC', 'ML', 'MR', 'MC', 'MC', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Double screen in front of defence', 'Strike partnership'],
        'strengths_it': [
            'Superiorita numerica a centrocampo',
            'Doppio schermo davanti alla difesa',
            "Coppia d'attacco"
        ],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'MC': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-4-1-2', '4-4-2 C (Classic)', '3W-3N-3W-1'],
        'defense_count': 3
    },
    {
        'id': '3w3n3w1',
        'name': '3W-3N-3W-1',
        'description_en': '3W-3N-3W-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-3N-3W-1 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'MC', 'MC', 'MC', 'AML', 'AMC', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Good width'],
        'strengths_it': ['Superiorita numerica a centrocampo', 'Buona ampiezza di gioco'],
        'weaknesses_en': ['Defensive flanks exposed to counters'],
        'weaknesses_it': ['Fasce difensive esposte ai contropiedi'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑',
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': ['3N-2W-2-1-2'],
        'vulnerable_to': [],
        'defense_count': 3
    },
    {
        'id': '31321tikitaka',
        'name': '3-1-3-2-1 (Tiki-taka)',
        'description_en': '3-1-3-2-1 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3-1-3-2-1 con difesa a 3. Massimizza il possesso palla e la creativita tra le linee.',
        'positions': ['GK', 'DC', 'DC', 'DC', 'DMC', 'MC', 'MC', 'MC', 'AML', 'AMR', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'DMC shielding the defence'],
        'strengths_it': [
            'Massimizza il possesso palla e la creativita tra le linee.',
            'Superiorita numerica a centrocampo',
            'DMC a protezione della difesa'
        ],
        'weaknesses_en': [
            'Defensive flanks exposed to counters',
            'Lacks width: vulnerable to opposition wingers',
            'Isolated striker without support'
        ],
        'weaknesses_it': [
            'Richiede Team Balance 9.2-10 per non crollare fisicamente.',
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Down Both Flanks',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Down Both Flanks',
                'focus_passing_it': 'Per entrambe le fasce',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'AML': '↑',
                    'AMR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['4-3N-3', '4-3N-2W-1', '4-5-1 V-Style'],
        'defense_count': 3
    },
    {
        'id': '3w2n3n2',
        'name': '3W-2N-3N-2',
        'description_en': '3W-2N-3N-2 shape with a back 3. Midfield numerical advantage',
        'description_it': 'Modulo 3W-2N-3N-2 con difesa a 3. Superiorita numerica a centrocampo',
        'positions': ['GK', 'DL', 'DC', 'DR', 'MC', 'MC', 'AMC', 'AMC', 'AMC', 'ST', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Midfield numerical advantage', 'Strike partnership'],
        'strengths_it': ['Superiorita numerica a centrocampo', "Coppia d'attacco"],
        'weaknesses_en': ['Defensive flanks exposed to counters', 'Lacks width: vulnerable to opposition wingers'],
        'weaknesses_it': [
            'Fasce difensive esposte ai contropiedi',
            'Manca ampiezza: vulnerabile alle ali avversarie'
        ],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Mixed',
            'counter_attack': False,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact, hit them on the break with long balls.',
                'tip_it': 'Resta compatto e riparti con palle lunghe.',
                'arrows': {
                    'DL': '↓',
                    'DR': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': "Play your natural game and exploit your shape's strengths.",
                'tip_it': 'Gioca il tuo gioco naturale sfruttando i punti di forza del modulo.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high and keep the ball in their half.',
                'tip_it': "Pressa alto e tieni palla nella loro meta' campo.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-5-2 F (Flat)', '4-4-2 C (Classic)', '5-4-1 F (Flat)'],
        'defense_count': 3
    },
    {
        'id': '423namc1',
        'name': '4-2-3N(AMC)-1',
        'description_en': '4-2-3-1 variant with three narrow AMCs behind the striker.',
        'description_it': 'Variante del 4-2-3-1 con tre AMC stretti alle spalle della punta.',
        'positions': ['GK', 'DL', 'DC', 'DC', 'DR', 'MC', 'MC', 'AMC', 'AMC', 'AMC', 'ST'],
        'category_en': 'Attacking',
        'category_it': 'Offensiva',
        'strengths_en': ['Overloads the central attacking zone', 'Creative play between the lines'],
        'strengths_it': ['Sovraccarica la trequarti centrale', 'Gioco creativo tra le linee'],
        'weaknesses_en': ['No natural width', 'Flanks exposed to opposition wingers'],
        'weaknesses_it': ['Nessuna ampiezza naturale', 'Fasce esposte alle ali avversarie'],
        'tactic_type_en': 'Attacking',
        'tactic_type_it': 'Offensiva',
        'recommended_tactics': {
            'mentality': 'Normal',
            'focus_passing': 'Through the Middle',
            'passing_style': 'Short',
            'counter_attack': True,
            'pressing': 'Medium',
            'tackling': 'Normal',
            'marking': 'Zonal',
            'offside_trap': False
        },
        'opponent_settings': {
            'strong': {
                'mentality': 'Defensive',
                'mentality_it': 'Difensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Long',
                'passing_style_it': 'Lunghi',
                'counter_attack': True,
                'pressing': 'Low',
                'pressing_it': 'Basso',
                'tackling': 'Easy',
                'tackling_it': 'Facile',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Stay compact centrally and break with quick vertical balls.',
                'tip_it': 'Compatto al centro, riparti con verticalizzazioni rapide.',
                'arrows': {
                    'DC': '↓'
                }
            },
            'equal': {
                'mentality': 'Normal',
                'mentality_it': 'Normale',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Mixed',
                'passing_style_it': 'Misti',
                'counter_attack': True,
                'pressing': 'Medium',
                'pressing_it': 'Medio',
                'tackling': 'Normal',
                'tackling_it': 'Normale',
                'marking': 'Zonal',
                'marking_it': 'Zonale',
                'offside_trap': False,
                'tip_en': 'Feed the three AMCs between the lines.',
                'tip_it': 'Cerca i tre AMC tra le linee.',
                'arrows': {
                    'MC': '↑'
                }
            },
            'weak': {
                'mentality': 'Attacking',
                'mentality_it': 'Offensiva',
                'focus_passing': 'Through the Middle',
                'focus_passing_it': 'Al Centro',
                'passing_style': 'Short',
                'passing_style_it': 'Corti',
                'counter_attack': False,
                'pressing': 'High',
                'pressing_it': 'Alto',
                'tackling': 'Hard',
                'tackling_it': 'Duro',
                'marking': 'Man-to-Man',
                'marking_it': 'Uomo a Uomo',
                'offside_trap': True,
                'tip_en': 'Press high, overload the box with the AMC trio.',
                'tip_it': "Pressa alto, riempi l'area col trio di AMC.",
                'arrows': {
                    'DL': '↑',
                    'DR': '↑'
                }
            }
        },
        'effective_against': [],
        'vulnerable_to': ['3-1-4-2', '4-4-2 C (Classic)', '3W-2N-3W-2'],
        'defense_count': 4
    }
]

# ==================== COUNTER ENGINE v6 — FRECCE COMPLETE + META 2025 ====================
# Per ogni scenario: TUTTE le posizioni del modulo consigliato
# ctrl: SI/NO | press: Alto/Basso | fuo: SI/NO
# Frecce: ogni entry copre TUTTI i ruoli del modulo consigliato

COUNTER_ENGINE = [
    {
        'av': '3N-5-2 F',
        'cat': 'att',
        'forte': {
            'mod': '4-2-3-1',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '5 MF avversari al centro: 2 MC tuoi coprono. AML/AMR pronti al contropiede sulle fasce libere'
        },
        'pari': {
            'mod': '4-3N-2W-1',
            'alt': '4-2-3-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Sfrutta terzini scoperti avversari. Non aprire il centro'
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '3-5-2 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Nessun terzino avversario: aggredisci con 4 MC sulle fasce spalancate'
        }
    },
    {
        'av': '3W-5-2 F',
        'cat': 'att',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Ali larghe: DMC+2MC coprono il centro. AML/AMR in contropiede'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Mantieni compattezza. Le ali W spingono alto e lasciano spazio dietro'
        },
        'debole': {
            'mod': '3-1-3N-2W-1',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'MC': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '3 DC senza terzini avversari: spazio laterale enorme. Sfruttalo con le ali'
        }
    },
    {
        'av': '3N-4-3',
        'cat': 'att',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '5 difensori bloccano 3 attaccanti. Non uscire mai dalla posizione. Contropiede veloce'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '↑'
            },
            'w': '4-3-3 pericoloso sulle fasce. ST con freccia avanti per occupare i 3 DC'
        },
        'debole': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Hard',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 MC domina il centro vs 3 MC avversari. Sfrutta mancanza DMC'
        }
    },
    {
        'av': '3W-4-3',
        'cat': 'att',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '5-4-1 F (Flat)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '3 attaccanti larghi: non avanzare mai i terzini. DMC fondamentale'
        },
        'pari': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Hexagon sfrutta le fasce scoperte del 3-4-3 che non ha terzini'
        },
        'debole': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '3-5-2 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'AML': '↑',
                'MC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '5 MF vs 3 MC: dominio totale al centro poi sfonda in ampiezza'
        }
    },
    {
        'av': '3W-1-4-2',
        'cat': 'att',
        'forte': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': 'ND copre il centro denso. Evita di avanzare i terzini'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Mantieni diamond compatto. AMC sfrutta lo spazio dietro i loro MC'
        },
        'debole': {
            'mod': '3-4-1-2',
            'alt': '3-5-2 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Aggredisci le fasce difensive aperte del 3-1-4-2 senza terzini'
        }
    },
    {
        'av': '3N-1-4-2',
        'cat': 'att',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '4 MC avversari al centro: DMC è lo scudo. Sfrutta le fasce in contropiede'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Avversario senza terzini: sfrutta le fasce con AML/AMR alti'
        },
        'debole': {
            'mod': '3-5-1-1 V',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 MF vs loro 4+1: schiacciante. Aggredisci le fasce aperte'
        }
    },
    {
        'av': '3N-5-2 V',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Butterfly: 2 DMC schermo vs loro centro affollato. AML/AMR in contropiede'
        },
        'pari': {
            'mod': '4-3N-2W-1',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Sfrutta le fasce libere: il 3-5-2 V non ha terzini'
        },
        'debole': {
            'mod': '3-1-3N-3',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Hard',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↑',
                'MC': '↑',
                'ST': '—'
            },
            'w': 'Sovraffolla il centrocampo poi sfonda in ampiezza. DMC con freccia avanti'
        }
    },
    {
        'av': '3N-1-3W-1-2 D (Dandelion)',
        'cat': 'att',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Dandelion: 3N+3W affolla tutto. Sfrutta le fasce libere in contropiede'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-1-2-1-2 WD (Wide Diamond)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Il 4-4-2 bilancia bene sia centro che fasce contro il Dandelion'
        },
        'debole': {
            'mod': '3-5-1-1 V',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 MF domina il loro 3+3+1: nessuno può seguire tutti i tuoi giocatori'
        }
    },
    {
        'av': '3N-2-2-2-1 B (Butterfly 3N)',
        'cat': 'att',
        'forte': {
            'mod': '3N-5-2 F',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Butterfly 3DC: 2 DMC + 2 MC + 2 AML/AMR. Molto bilanciato. Sii paziente'
        },
        'pari': {
            'mod': '4-3N-2W-1',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Sfrutta fasce libere. Il Butterfly non ha terzini'
        },
        'debole': {
            'mod': '3N-5-2 F',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Hard',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 MF attaccante vs loro 2 DMC: dominio assoluto'
        }
    },
    {
        'av': '3W-2DMC-3W-1-1 ML (Maple Leaf)',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-1-4-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': "Counter difensivo verificato: il Butterfly chiude il centro con 2 DMC e regge l'urto dei loro esterni alti."
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': '4-5-1 V equilibrato: il DMC scherma, le ali ripartono nelle fasce lasciate scoperte dai loro 3W.'
        },
        'debole': {
            'mod': '3N-1-4-2',
            'alt': '3-4-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Attacca col 3N-1-4-2: aggira la mediana folta sulle fasce, 2 punte contro i 3 DC larghi.'
        }
    },
    {
        'av': '4-4-2 C (Classic)',
        'cat': 'neu',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Centro',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '4-4-2 forte in ampiezza: Butterfly copre tutto. Evita di allargare il gioco'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AMC': '↑',
                'ST': '↑'
            },
            'w': 'ND attacca il centro debole del 4-4-2. AMC e ST con frecce avanti'
        },
        'debole': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '3-5-2 F (Flat)',
            'men': 'Molto Offensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Hard',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'DMC': '—',
                'MC': '↑',
                'AMC': '↑',
                'ST': '↑'
            },
            'w': 'Schiaccia il centro: il 4-4-2 non ha AMC. DMC neutro per trasformarsi in MC'
        }
    },
    {
        'av': '4-5-1 V-Style',
        'cat': 'neu',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': "Speculare: chi sbaglia primo perde. Sii paziente, aspetta l'errore avversario"
        },
        'pari': {
            'mod': '4-3N-3',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'ST': '—'
            },
            'w': '3 attaccanti contro DMC+2MC: premi sulle fasce dove sono scoperti'
        },
        'debole': {
            'mod': '3-3-1-3',
            'alt': '3W-1-2-3W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'MC': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': '3 attaccanti fanno saltare la loro linea difensiva a 4. AMC tra le linee'
        }
    },
    {
        'av': '4-5-1 F (Flat)',
        'cat': 'neu',
        'forte': {
            'mod': '4-1-4-1',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '5 MC piatti difensivi ma prevedibili. Contropiede veloce sulle fasce'
        },
        'pari': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '3-5-2 F (Flat)',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'AML': '—',
                'MC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': '3 DC + 5 MF: match-up paritario. Usa passaggi lunghi per sfuggire al pressing'
        },
        'debole': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-3N-3',
            'men': 'Offensiva',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Premi alto: 4-5-1 F non ha attaccanti pronti al contropiede rapido'
        }
    },
    {
        'av': '4-1-2-1-2 ND (Narrow Diamond)',
        'cat': 'neu',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'ND pericoloso al centro: AML/AMR sfruttano i fianchi totalmente vuoti'
        },
        'pari': {
            'mod': '3N-5-2 V',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Flanchi liberi del ND: attacca con AML e AMR che non hanno avversari'
        },
        'debole': {
            'mod': '3N-5-2 V',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Hard',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Aggredisci: il ND non ha terzini né ali. Completamente aperto sui lati'
        }
    },
    {
        'av': '4-2-2-2 H (Hexagon)',
        'cat': 'neu',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '3-2-2-2-1 B (Butterfly)',
            'men': 'Difensiva',
            'pass': 'Centro',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Hexagon con AML/AMR alti: DMC fondamentale schermo al centro'
        },
        'pari': {
            'mod': '3N-4-1-2',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '↓',
                'ML': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '4 MC vs loro 2 MC: sovraffolla il centro e bypassa le loro ali'
        },
        'debole': {
            'mod': '3N-4-3',
            'alt': '3-4-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '3 attaccanti vs loro 2 MC soli: troppo da gestire. Dominio assoluto'
        }
    },
    {
        'av': '4-3N-2W-1',
        'cat': 'neu',
        'forte': {
            'mod': '4-4-1-1',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 MC + 2 AM: molto bilanciato. 4-4-1-1 copre bene sia centro che fasce'
        },
        'pari': {
            'mod': '3-1-4-1-1',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': '★ META 2025: 3-1-4-1-1 sfrutta le fasce con ML/MR e trova AMC tra le linee'
        },
        'debole': {
            'mod': '3-1-4-1-1',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Domina con 4 MC + AMC. I loro 2W avanzati si ritrovano isolati'
        }
    },
    {
        'av': '4-1-4-1',
        'cat': 'neu',
        'forte': {
            'mod': '4-2-3-1',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '4-1-4-1 è solido: DMC+4MF controllano. Sfrutta le fasce in contropiede'
        },
        'pari': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '3W-4-3',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Hexagon: AML/AMR sfruttano lo spazio tra ML/MR e terzini avversari'
        },
        'debole': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-3N-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'AML': '↑',
                'MC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Premi alto con 5 MF: sovrasta il loro centrocampo'
        }
    },
    {
        'av': '4-4-1-1',
        'cat': 'neu',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': "L'AMC avversario è la minaccia principale: DMC lo neutralizza. AML/AMR liberi"
        },
        'pari': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '5 MF vs 4 MF: vantaggio numerico al centro. Sfrutta le fasce'
        },
        'debole': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-3N-3',
            'men': 'Offensiva',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Con netto vantaggio: 5 MC + 2 ST vs loro 4 MF. Aggredisci da subito'
        }
    },
    {
        'av': '4-2-3-1',
        'cat': 'neu',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': "5 difensori bloccano l'AMC. Contropiede dalle fasce con ML/MR"
        },
        'pari': {
            'mod': '4-1-4-1',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'DMC copre il loro AMC. ML/MR sfruttano le fasce. Non avanzare i terzini'
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '4-3N-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '4 MC contro loro 2: domina il centrocampo. DMC neutro'
        }
    },
    {
        'av': '3-4-1-2',
        'cat': 'neu',
        'forte': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': 'Debolezza del 3-4-1-2: le fasce difensive aperte. ND aspetta e contrattacca'
        },
        'pari': {
            'mod': '4-1-3W-1-1',
            'alt': '3-1-3W-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'DMC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '—',
                'ST': '—'
            },
            'w': '★ Ala skewata stesso lato del ST. Fasce scoperte del 3-4-1-2 = vulnerabilità'
        },
        'debole': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-1-3W-1-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 MF + attacco sulle fasce aperte. Nessun terzino avversario = distruttivo'
        }
    },
    {
        'av': '3N-1-4-1-1',
        'cat': 'att',
        'meta': True,
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '★ META: 3-1-4-1-1 molto pericoloso. DMC marca il loro AMC. Sfrutta le fasce vuote'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'ND risponde al loro 1-1: centro contro centro. AMC marca il loro AMC'
        },
        'debole': {
            'mod': '3-1-4-1-1',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Specchia la loro formazione con più qualità. Tutte le frecce avanti'
        }
    },
    {
        'av': '3W-1-4-1-1',
        'cat': 'att',
        'meta': True,
        'forte': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'AML': '—',
                'MC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': '4 MC avversari affollano il centro. 5 MF bilancia il numero'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Sfrutta fasce scoperte. Il loro 1 AMC va marcato da DMC'
        },
        'debole': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'AML': '↑',
                'MC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Domina il centrocampo poi apri sulle fasce. Nessun terzino = spazio enorme'
        }
    },
    {
        'av': '4-1-3N-1-1',
        'cat': 'neu',
        'meta': True,
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '3-2-2-2-1 B (Butterfly)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '★ META: 4-1-3-1-1 molto forte. DMC marca il loro AMC. Sfrutta le fasce con AML/AMR'
        },
        'pari': {
            'mod': '3-1-4-1-1',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': '★ Contro meta: usa 3-1-4-1-1 anche tu. 4 MC + AMC vs loro 3 MC + AMC'
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '4 MC + DMC in avanti domina il loro 3N+AMC. Sfonda sulle fasce'
        }
    },
    {
        'av': '4-1-3W-1-1',
        'cat': 'neu',
        'meta': True,
        'forte': {
            'mod': '5-1DMC-2-2',
            'alt': '4-5-1 F (Flat)',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '5 difensori + DMC schermo bloccano le 3 ali avversarie. AML/AMR in contropiede'
        },
        'pari': {
            'mod': '4-4-1-1',
            'alt': '4-1-4-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'ML/MR coprono le loro 3W ali. AMC dietro è la minaccia: marcalo'
        },
        'debole': {
            'mod': '3-1-4-1-1',
            'alt': '4-4-1-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': '4 MC con forza sulle fasce: sovrasta il loro 1 MC solo. DMC in avanti'
        }
    },
    {
        'av': '3-1-3-2-1 (Tiki-taka)',
        'cat': 'att',
        'meta': True,
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Difensiva',
            'pass': 'Centro',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '★ LevelWinner 2024: Tiki-taka senza terzini. Blocca centro e sfrutta fasce in contropiede'
        },
        'pari': {
            'mod': '4-3N-2W-1',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Le fasce sono libere: 3 DC senza terzini. Aggredisci con AML/AMR'
        },
        'debole': {
            'mod': '4-3N-3',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'MC': '↑',
                'ST': '—'
            },
            'w': '3 attaccanti vs loro 3 DC soli: superiorità numerica in attacco'
        }
    },
    {
        'av': '3-1-3-1-2',
        'cat': 'att',
        'meta': True,
        'forte': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '★ LevelWinner 2024: Route One su fasce vuote. 5 MF bilancia il loro centrocampo'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '3-5-2 F (Flat)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Sfrutta le fasce: i loro ML/MR sono bassi (posizione difensiva). AML/AMR liberi'
        },
        'debole': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'AML': '↑',
                'MC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Aggredisci sulle fasce con 5 MF. Il loro AMC resta isolato tra le linee'
        }
    },
    {
        'av': '5-4-1 F (Flat)',
        'cat': 'dif',
        'forte': {
            'mod': '4-3N-2W-1',
            'alt': '4-3N-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'MC': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Bus park: usa pazienza. Terzini alti sfruttano lo spazio tra i loro 5'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': 'ST con freccia avanti per occupare la difesa a 5. ML/MR sfruttano le fasce'
        },
        'debole': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Molto Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': 'Aggredisci da subito: il bus si sfascia sotto pressione continua alta'
        }
    },
    {
        'av': '5-3N-2',
        'cat': 'dif',
        'forte': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': '3 MC al centro: usa le fasce dove sono completamente scoperti'
        },
        'pari': {
            'mod': '3N-4-1-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'ML': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Pazienza + variazioni tra centro e fasce. DMC neutro per equilibrio'
        },
        'debole': {
            'mod': '3N-4-1-2',
            'alt': '3-5-2 F (Flat)',
            'men': 'Molto Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'MC': '↑',
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': 'Sovrasta: 4 MC + 2 ST contro 3 MC. Dominio assoluto sulle fasce'
        }
    },
    {
        'av': '5-3W-2',
        'cat': 'dif',
        'forte': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↑',
                'DC': '↓',
                'DR': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': 'Ali larghe avversarie: attacca per il centro dove sono sguarniti'
        },
        'pari': {
            'mod': '3N-4-1-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'MC': '↑',
                'ML': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '4 MC martellano il centro: 5-3W-2 non ha DMC di protezione. DMC in avanti'
        },
        'debole': {
            'mod': '3N-5-2 V',
            'alt': '3-5-2 F (Flat)',
            'men': 'Molto Offensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Hard',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 MC dominano il centro. Le loro 3W restano alte e inutili sotto pressing'
        }
    },
    {
        'av': '5-2-1-2 X (X-Style)',
        'cat': 'dif',
        'forte': {
            'mod': '4-1-2N-1-2',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '—',
                'MC': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'X-Style con DML/DMR: gioca stretto al centro. DMC neutro per gestire'
        },
        'pari': {
            'mod': '3N-1-4-2',
            'alt': '4-1-2N-1-2',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': '4 MC vs loro 1 AMC: dominio assoluto al centro'
        },
        'debole': {
            'mod': '3N-1-4-2',
            'alt': '3-5-2 F (Flat)',
            'men': 'Molto Offensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Hard',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': 'Sbaraglia il loro 1 AMC con 4 MC. DMC in avanti. Nessuno scampo'
        }
    },
    {
        'av': '4-3-2-1 XT (Xmas Tree)',
        'cat': 'neu',
        'forte': {
            'mod': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
            'alt': '4-5-1 F (Flat)',
            'men': 'Difensiva',
            'pass': 'Centro',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Tower + 2 DMC schermo vs Xmas Tree. AML/AMR pronti al contropiede'
        },
        'pari': {
            'mod': '3-1-5-1 AMC',
            'alt': '4-5-1 F (Flat)',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '5 MF affolla il centro vs loro 3N+2AMC. Nessun DMC avversario'
        },
        'debole': {
            'mod': '3-1-5-1 AMC',
            'alt': '4-3N-3',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '↑',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'XT senza DMC: il centro è completamente aperto. Sfonda con tutto'
        }
    },
    {
        'av': '3-1-5-1 AMC',
        'cat': 'neu',
        'meta': True,
        'forte': {
            'mod': '4-3-3',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '↑',
                'AML': '↑',
                'AMR': '↑'
            },
            'w': "★ VS 3-1-5-1 FORTE: Marca a uomo l'AMC! Chiudi il centro, contropiede sulle fasce libere. MR-ML veloci per sfruttare 3 difensori"
        },
        'pari': {
            'mod': '4-2-3-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '↓',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'VS 3-1-5-1 PARI: Il loro AMC è il perno - limita il suo spazio. Usa 2 DMC per schermarlo. Attacca le fasce: solo 3 difensori!'
        },
        'debole': {
            'mod': '4-3-3',
            'alt': '3-5-2 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DC': '—',
                'DR': '↑',
                'MC': '↑',
                'ST': '↑',
                'AML': '↑',
                'AMR': '↑'
            },
            'w': '★ VS 3-1-5-1 DEBOLE: Pressing totale! Solo 3 DC + 1 DMC. Superiorità numerica ovunque. Attacca le fasce con DL/DR avanti!'
        }
    },
    {
        'av': '4-3-3',
        'cat': 'neu',
        'meta': True,
        'forte': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-1-3-1-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ML': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': "Compatto col 4-4-2. Lanci lunghi alla coppia d'attacco contro tridenti veloci"
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-1-3-1-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Medio',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '—',
                'DR': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Densità centrale a 4 in mediana. Le tue fasce attaccano i loro terzini'
        },
        'debole': {
            'mod': '4-1-3-2',
            'alt': '4-2-3-1',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Uomo',
            'fuo': 'SI',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'DMC': '—',
                'MC': '↑',
                'ST': '↑'
            },
            'w': 'Sovraccarica il centro col DMC ancora. Pressing alto sui loro DC'
        }
    },
    {
        'av': '5-2-2(AML-AMR)-1',
        'cat': 'dif',
        'forte': {
            'mod': '3W-1-2-3W-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'AML': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': 'Difesa a 3 wide e 4 dietro. Stop alle loro AML/AMR coi tuoi terzini bassi'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3-3',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'ML': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Spingi i terzini per attaccare le loro fasce. Le ali avversarie restano basse'
        },
        'debole': {
            'mod': '4-3-3',
            'alt': '3-4-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': '5 attaccanti vs 5 difensori. Sfonda dalle fasce con cross continui'
        }
    },
    {
        'av': '4-1-3W-2',
        'cat': 'neu',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '5-3W-2',
            'men': 'Molto Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '—',
                'ML': '↓',
                'MR': '↓',
                'ST': '—'
            },
            'w': 'Catenaccio. 5 dietro + 4 in mediana per chiudere le loro ali wide'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Medio',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DMC': '↓',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'V-Style col DMC ancora. Ali sopra per sfruttare gli spazi che lasciano'
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '3-5-2 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': 'Sovraccarica il centro col DMC. Ali coi terzini sotto pressione'
        }
    },
    {
        'av': '3-1-4-2',
        'cat': 'att',
        'forte': {
            'mod': '5-3W-2',
            'alt': '5-3N-2',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': '5 dietro per neutralizzare le loro 2 punte. Le tue 2 punte fanno contropiede'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Specchiati col 4-4-2. La tua difesa a 4 batte la loro a 3 sulle fasce'
        },
        'debole': {
            'mod': '3-4-3',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': 'Tridente offensivo per sopraffare la loro difesa a 3'
        }
    },
    {
        'av': '3W-2N-3N-2',
        'cat': 'dif',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-1-4-1',
            'men': 'Molto Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ML': '↓',
                'MR': '↓',
                'ST': '—'
            },
            'w': 'Centro affollato. Aspetta gli errori e riparti in contropiede col ST'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-5-1 F (Flat)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Sfrutta le fasce: il loro centro è denso ma le ali deboli'
        },
        'debole': {
            'mod': '3-5-2 F (Flat)',
            'alt': '3-4-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': 'Pressing alto. Centrocampo a 5 ribalta il loro centro affollato'
        }
    },
    {
        'av': '3-5-2 F (Flat)',
        'cat': 'att',
        'forte': {
            'mod': '4-3N-2W-1',
            'alt': '3-2-2-2-1 B (Butterfly)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-3N-2W-1 e riparti in contropiede'
        },
        'pari': {
            'mod': '4-3N-2W-1',
            'alt': '3-2-2-2-1 B (Butterfly)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Attacca le fasce per sfruttare l'assenza di terzini nella difesa a tre"
        },
        'debole': {
            'mod': '4-3N-2W-1',
            'alt': '3-2-2-2-1 B (Butterfly)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-3N-2W-1 e domina con pressing aggressivo'
        }
    },
    {
        'av': '3-5-2 V (V-Style)',
        'cat': 'att',
        'forte': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-3N-2W-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-2-2-2 H e riparti in contropiede'
        },
        'pari': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': "L'Hexagon bilancia la copertura del campo contro la spinta laterale"
        },
        'debole': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-2-2-2 H e domina con pressing aggressivo'
        }
    },
    {
        'av': '3-4-3',
        'cat': 'att',
        'forte': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Molto Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-2-2-2 H e riparti in contropiede'
        },
        'pari': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Proteggi i fianchi e colpisci in contropiede negli spazi esterni'
        },
        'debole': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-2-2-2 H e domina con pressing aggressivo'
        }
    },
    {
        'av': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
        'cat': 'att',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-5-1 V-Style e riparti in contropiede'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': "4-5-1 V-Style: counter principale da fonte, controlla la mediana e mantieni l'ampiezza."
        },
        'debole': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3-3',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'ML': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Mantieni ampiezza col 4-4-2 Classic: allarga il muro centrale, cross per le due punte.'
        }
    },
    {
        'av': '5-1DMC-2-2',
        'cat': 'dif',
        'forte': {
            'mod': '4-1-3W-1-1',
            'alt': '4-1-4-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-1-3W-1-1 e riparti in contropiede'
        },
        'pari': {
            'mod': '4-1-3W-1-1',
            'alt': '4-1-4-1',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Centrocampo versatile per scardinare la densità della difesa a 5'
        },
        'debole': {
            'mod': '4-1-3W-1-1',
            'alt': '4-1-4-1',
            'men': 'Offensiva',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-1-3W-1-1 e domina con pressing aggressivo'
        }
    },
    {
        'av': '4-1-3-1W-1',
        'cat': 'neu',
        'forte': {
            'mod': '4-1-3-1-1',
            'alt': '4-5-1 V-Style',
            'men': 'Molto Difensiva',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-1-3-1-1 e riparti in contropiede'
        },
        'pari': {
            'mod': '4-1-3-1-1',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'DMC e MC arretrati sono vitali per ottenere clean sheet'
        },
        'debole': {
            'mod': '4-1-3-1-1',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-1-3-1-1 e domina con pressing aggressivo'
        }
    },
    {
        'av': '3-1-4-1-1',
        'cat': 'att',
        'forte': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-1-2-1-2 ND e riparti in contropiede'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Il diamante stretto domina il possesso neutralizzando i mediani'
        },
        'debole': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Centro',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-1-2-1-2 ND e domina con pressing aggressivo'
        }
    },
    {
        'av': '4-1-2-2-1',
        'cat': 'neu',
        'forte': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-2-2-2 H e riparti in contropiede'
        },
        'pari': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Sfrutta le fasce se l'avversario concentra trequartisti al centro"
        },
        'debole': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-2-2-2 H e domina con pressing aggressivo'
        }
    },
    {
        'av': 'False Nine + Wingers',
        'cat': 'att',
        'forte': {
            'mod': '4-1-3-1-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Molto Difensiva',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-1-3-1-1 e riparti in contropiede'
        },
        'pari': {
            'mod': '4-1-3-1-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Arretra DMC e MC per togliere spazio al Falso Nove tra le linee'
        },
        'debole': {
            'mod': '4-1-3-1-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-1-3-1-1 e domina con pressing aggressivo'
        }
    },
    {
        'av': '4-2-4',
        'cat': 'att',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Molto Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 5-4-1 F e riparti in contropiede'
        },
        'pari': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Parcheggia l'autobus contro i 4 attaccanti e colpisci in contropiede"
        },
        'debole': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 5-4-1 F e domina con pressing aggressivo'
        }
    },
    {
        'av': '4-1-3-1-1',
        'cat': 'neu',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-5-1 V e riparti in contropiede'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Allarga il gioco per aggirare la densità centrale e rifornire la punta'
        },
        'debole': {
            'mod': '4-5-1 V-Style',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-5-1 V e domina con pressing aggressivo'
        }
    },
    {
        'av': '5-3-2',
        'cat': 'dif',
        'forte': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3-3',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-4-2 C e riparti in contropiede'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3-3',
            'men': 'Offensiva',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Alza baricentro e ritmo per scardinare il muro a 5'
        },
        'debole': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-3-3',
            'men': 'Molto Offensiva',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-4-2 C e domina con pressing aggressivo'
        }
    },
    {
        'av': '3-1-3-2W-1',
        'cat': 'att',
        'forte': {
            'mod': '4-1-4-1',
            'alt': '4-5-1 V-Style',
            'men': 'Molto Difensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-1-4-1 e riparti in contropiede'
        },
        'pari': {
            'mod': '4-1-4-1',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Proteggi i fianchi e attacca centralmente dove la difesa a 3 è fragile'
        },
        'debole': {
            'mod': '4-1-4-1',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Centro',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-1-4-1 e domina con pressing aggressivo'
        }
    },
    {
        'av': '3-3-1-3',
        'cat': 'att',
        'forte': {
            'mod': '4-1-4-1',
            'alt': '4-5-1 V-Style',
            'men': 'Molto Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-1-4-1 e riparti in contropiede'
        },
        'pari': {
            'mod': '4-1-4-1',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Il 4-1-4-1 compatto neutralizza la fantasia di questo modulo asimmetrico'
        },
        'debole': {
            'mod': '4-1-4-1',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-1-4-1 e domina con pressing aggressivo'
        }
    },
    {
        'av': '4-2-2-1-1',
        'cat': 'dif',
        'forte': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Normale',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-4-2 C e riparti in contropiede'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Offensiva',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Assetto propositivo per superare il doppio schermo davanti alla difesa'
        },
        'debole': {
            'mod': '4-4-2 C (Classic)',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Molto Offensiva',
            'pass': 'Misto',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-4-2 C e domina con pressing aggressivo'
        }
    },
    {
        'av': '4-1-1-3-1',
        'cat': 'att',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Resta compatto col 4-5-1 V e riparti in contropiede'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Basso',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Il V-Style versatile è la risposta migliore a questa variante fluida'
        },
        'debole': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-3-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Spingi alto col 4-5-1 V e domina con pressing aggressivo'
        }
    },
    {
        'av': '4-3-1-2',
        'cat': 'neu',
        'forte': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-5-1 V-Style e riparti in contropiede"
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Allarga il gioco e attacca le fasce dove il diamante non difende'
        },
        'debole': {
            'mod': '4-5-1 V-Style',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-5-1 V-Style con pressing e ritmo"
        }
    },
    {
        'av': '3-1-2-1-3',
        'cat': 'att',
        'forte': {
            'mod': '4-1-3-1-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-1-3-1-1 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-1-3-1-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': "DMC e MC arretrati neutralizzano l'AMC; difesa a 4 contro 3 punte"
        },
        'debole': {
            'mod': '4-1-3-1-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'MC': '↑',
                'AMC': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-1-3-1-1 con pressing e ritmo"
        }
    },
    {
        'av': '3-4-2-1',
        'cat': 'neu',
        'forte': {
            'mod': '4-3-3',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-3-3 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-3-3',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': '4-3-3 sfrutta gli spazi lasciati dai wing-back avanzati'
        },
        'debole': {
            'mod': '4-3-3',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-3-3 con pressing e ritmo"
        }
    },
    {
        'av': '5-2-3',
        'cat': 'dif',
        'forte': {
            'mod': '4-3-3',
            'alt': '3-5-2 F (Flat)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-3-3 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-3-3',
            'alt': '3-5-2 F (Flat)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Domina il centrocampo a 3 contro 2 e scardina con cross continui'
        },
        'debole': {
            'mod': '4-3-3',
            'alt': '3-5-2 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-3-3 con pressing e ritmo"
        }
    },
    {
        'av': '4-2-2-2 N (Narrow)',
        'cat': 'neu',
        'forte': {
            'mod': '4-3-3',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-3-3 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-3-3',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Allarga sulle fasce dove non ci sono ali avversarie'
        },
        'debole': {
            'mod': '4-3-3',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-3-3 con pressing e ritmo"
        }
    },
    {
        'av': '3-1-4-2 W',
        'cat': 'att',
        'forte': {
            'mod': '4-2-3-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-2-3-1 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-2-3-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': "L'AMC del 4-2-3-1 sfrutta lo spazio tra DMC e linea difensiva avversaria"
        },
        'debole': {
            'mod': '4-2-3-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-2-3-1 con pressing e ritmo"
        }
    },
    {
        'av': '4-2-3-1 Attack',
        'cat': 'att',
        'forte': {
            'mod': '4-1-3N-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-1-3N-2 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-1-3N-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': "DMC stretto blocca l'AMC, due MC tengono il centro"
        },
        'debole': {
            'mod': '4-1-3N-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'MC': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-1-3N-2 con pressing e ritmo"
        }
    },
    {
        'av': '4-2-3-1-2',
        'cat': 'neu',
        'forte': {
            'mod': '4-3-3',
            'alt': '3-5-2 F (Flat)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-3-3 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-3-3',
            'alt': '3-5-2 F (Flat)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Allarga il gioco: il centro è folto ma le fasce sono scoperte'
        },
        'debole': {
            'mod': '4-3-3',
            'alt': '3-5-2 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-3-3 con pressing e ritmo"
        }
    },
    {
        'av': '4-1-2-1-2 WD (Wide Diamond)',
        'cat': 'neu',
        'forte': {
            'mod': '4-3W-1-2',
            'alt': '4-1-4-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 4-3W-1-2 e riparti in contropiede"
        },
        'pari': {
            'mod': '4-3W-1-2',
            'alt': '4-1-4-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Centro denso ma fasce vulnerabili: spinge sui terzini avversari'
        },
        'debole': {
            'mod': '4-3W-1-2',
            'alt': '4-1-4-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 4-3W-1-2 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '3-2-2-2-1 B (Butterfly)',
        'cat': 'dif',
        'forte': {
            'mod': '3-4-1-2',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'ML': '↓',
                'DC': '↓',
                'MR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3-4-1-2 e riparti in contropiede"
        },
        'pari': {
            'mod': '3-4-1-2',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Aggressivita centrale per superare il doppio schermo difensivo'
        },
        'debole': {
            'mod': '3-4-1-2',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3-4-1-2 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '4-1-3N-2',
        'cat': 'neu',
        'forte': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-3N-2W-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'AML': '↓',
                'DC': '↓',
                'AMR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3-1-3N-2W-1 e riparti in contropiede"
        },
        'pari': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Tridente stretto avversario: contrastalo con difesa larga e contropiede'
        },
        'debole': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3-1-3N-2W-1 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '4-3N-3',
        'cat': 'neu',
        'forte': {
            'mod': '3-4-1-2',
            'alt': '4-1-4-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'ML': '↓',
                'DC': '↓',
                'MR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3-4-1-2 e riparti in contropiede"
        },
        'pari': {
            'mod': '3-4-1-2',
            'alt': '4-1-4-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Tridente stretto: doppio AMC sfonda l'area dietro le tre punte"
        },
        'debole': {
            'mod': '3-4-1-2',
            'alt': '4-1-4-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3-4-1-2 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '3N-1-2-1-3',
        'cat': 'att',
        'forte': {
            'mod': '3-1-3N-1-2',
            'alt': '4-1-3N-2',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3-1-3N-1-2 e riparti in contropiede"
        },
        'pari': {
            'mod': '3-1-3N-1-2',
            'alt': '4-1-3N-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Tre punte avversarie: doppia copertura centrale + due punte da contropiede'
        },
        'debole': {
            'mod': '3-1-3N-1-2',
            'alt': '4-1-3N-2',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'MC': '↑',
                'AMC': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3-1-3N-1-2 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '4-2-1-3',
        'cat': 'att',
        'forte': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-3N-2W-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'AML': '↓',
                'DC': '↓',
                'AMR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3-1-3N-2W-1 e riparti in contropiede"
        },
        'pari': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'AMC e tridente: chiudi al centro e attacca le fasce in transizione'
        },
        'debole': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3-1-3N-2W-1 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '4-1-1-2N-2',
        'cat': 'neu',
        'forte': {
            'mod': '3W-2N-1-3W-1',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3W-2N-1-3W-1 e riparti in contropiede"
        },
        'pari': {
            'mod': '3W-2N-1-3W-1',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Doppio AMC al centro: allarga gli esterni per togliere referenti'
        },
        'debole': {
            'mod': '3W-2N-1-3W-1',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↑',
                'DR': '↑',
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3W-2N-1-3W-1 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '3W-1-3N-1-2',
        'cat': 'neu',
        'forte': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'AML': '↓',
                'DC': '↓',
                'AMR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3-5-2 V e riparti in contropiede"
        },
        'pari': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-5-1 V-Style',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Asimmetrica: bilancia con il centrocampo a 5 e ali alte'
        },
        'debole': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'AML': '↑',
                'AMR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3-5-2 V con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '4-2N-1-2N-1',
        'cat': 'neu',
        'forte': {
            'mod': '3N-1-4-1-1',
            'alt': '4-1-3-2',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'ML': '↓',
                'DC': '↓',
                'MR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3N-1-4-1-1 e riparti in contropiede"
        },
        'pari': {
            'mod': '3N-1-4-1-1',
            'alt': '4-1-3-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Doppio DMC + doppio AMC: aggira con un attaccante che si abbassa'
        },
        'debole': {
            'mod': '3N-1-4-1-1',
            'alt': '4-1-3-2',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3N-1-4-1-1 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '5-1-1-1-2',
        'cat': 'dif',
        'forte': {
            'mod': '3N-5-2 V',
            'alt': '4-1-3-1-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'ML': '↓',
                'DC': '↓',
                'MR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3N-5-2 V e riparti in contropiede"
        },
        'pari': {
            'mod': '3N-5-2 V',
            'alt': '4-1-3-1-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'MC': '↓',
                'ST': '—'
            },
            'w': 'Piramide stretta: ali alte sfondano la difesa a 5 senza fasce coperte'
        },
        'debole': {
            'mod': '3N-5-2 V',
            'alt': '4-1-3-1-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3N-5-2 V con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '5-2W-2N-1',
        'cat': 'dif',
        'forte': {
            'mod': '3N-1-3W-1-2',
            'alt': '4-2-2-1-1',
            'men': 'Difensiva',
            'pass': 'Misto',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Facile',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'ML': '↓',
                'DC': '↓',
                'MR': '↓',
                'MC': '↓',
                'ST': '—'
            },
            'w': "Contro avversari piu' forti, resta compatto col 3N-1-3W-1-2 e riparti in contropiede"
        },
        'pari': {
            'mod': '3N-1-3W-1-2',
            'alt': '4-2-2-1-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Medio',
            'cont': 'Normale',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'DMC': '↓',
                'ST': '—'
            },
            'w': 'Difesa a 5 con esterni: doppia ala interna sfonda il muro centrale'
        },
        'debole': {
            'mod': '3N-1-3W-1-2',
            'alt': '4-2-2-1-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Corti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Duro',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'ML': '↑',
                'MR': '↑',
                'ST': '↑'
            },
            'w': "Contro avversari piu' deboli, spingi alto col 3N-1-3W-1-2 con pressing e marcatura aggressiva"
        }
    },
    {
        'av': '3N-5-1-1',
        'cat': 'att',
        'forte': {
            'mod': '3N-2W-2N-1-2',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Mediana folta avversaria: lascia il centro, contropiede rapido sulle corsie esterne. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '3-1-3N-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': 'Non sfidarli al centro (5 in mezzo): gira palla sulle fasce e attacca i mezzi spazi. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3-1-3N-1-2',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': '5 in mezzo ma pochi dietro: verticalizza presto, le ali attaccano la difesa corta'
        }
    },
    {
        'av': '3W-5-1-1',
        'cat': 'att',
        'forte': {
            'mod': '3N-2W-2N-1-2',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Mediana folta avversaria: lascia il centro, contropiede rapido sulle corsie esterne. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '3-1-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': 'Non sfidarli al centro (5 in mezzo): gira palla sulle fasce e attacca i mezzi spazi. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '5 in mezzo ma pochi dietro: verticalizza presto, le ali attaccano la difesa corta'
        }
    },
    {
        'av': '3W-5-2 V',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Mediana folta avversaria: lascia il centro, contropiede rapido sulle corsie esterne'
        },
        'pari': {
            'mod': '4-2-2-2 H (Hexagon)',
            'alt': '3-1-3N-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': 'Non sfidarli al centro (5 in mezzo): gira palla sulle fasce e attacca i mezzi spazi'
        },
        'debole': {
            'mod': '3-1-3N-1-2',
            'alt': '4-2-2-2 H (Hexagon)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': '5 in mezzo ma pochi dietro: verticalizza presto, le ali attaccano la difesa corta'
        }
    },
    {
        'av': '3W-2N-3W-2',
        'cat': 'att',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3W-5-2 F',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3W-5-2 F',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3N-2(DMC/MC)-3W-2',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '3-1-4-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3W-2(DMC/MC)-3W-2',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3-1-4-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3N-3(DMC/MC)-2W-2',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-3N-2W-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-3N-2W-1',
            'alt': '3-1-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3W-2N-2W-1-2',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '3W-5-2 V',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'AML': '—',
                'MC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3W-5-2 V',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3W-2N-2N-2W-1',
        'cat': 'att',
        'forte': {
            'mod': '3N-2W-3N-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3-4-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-4-1-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3N-2N-1-2W-2',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3-1-3W-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-1-3W-1-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3W-1-5-1',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-3N-2W-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Mediana folta avversaria: lascia il centro, contropiede rapido sulle corsie esterne'
        },
        'pari': {
            'mod': '4-3N-2W-1',
            'alt': '3-3N-3W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': 'Non sfidarli al centro (5 in mezzo): gira palla sulle fasce e attacca i mezzi spazi'
        },
        'debole': {
            'mod': '3-3N-3W-1',
            'alt': '4-3N-2W-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '5 in mezzo ma pochi dietro: verticalizza presto, le ali attaccano la difesa corta'
        }
    },
    {
        'av': '3W-1-3W-2N-1',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '3-5-2 V (V-Style)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'AML': '—',
                'MC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-5-2 V (V-Style)',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'AML': '↑',
                'MC': '—',
                'AMR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3N-1-3W-2N-1',
        'cat': 'att',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '3-5-1-1 V',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'AML': '—',
                'MC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-5-1-1 V',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3W-1-3W-1-2',
        'cat': 'att',
        'forte': {
            'mod': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3N-5-2 F',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3N-5-2 F',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3N-4-1-2',
        'cat': 'att',
        'forte': {
            'mod': '3N-2W-2N-1-2',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '3-1-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3W-4-1-2',
        'cat': 'att',
        'forte': {
            'mod': '3N-2W-2N-1-2',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Uomo',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-1-2-1-2 ND (Narrow Diamond)',
            'alt': '3-1-3N-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3-1-3N-1-2',
            'alt': '4-1-2-1-2 ND (Narrow Diamond)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '4-1(DMC)-2-3',
        'cat': 'neu',
        'forte': {
            'mod': '5-3N-2',
            'alt': '4-1-4-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '—',
                'ST': '—'
            },
            'w': "Avversario piu' forte: blocco ordinato, zona, e contropiede sulle fasce"
        },
        'pari': {
            'mod': '4-1-4-1',
            'alt': '3-1-4-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': "Equilibrio: vinci i duelli a centrocampo e sfrutta l'ampiezza"
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '4-1-4-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Sei superiore: pressing alto, possesso e ampiezza per allargare le maglie'
        }
    },
    {
        'av': '4-1-1-2W-2',
        'cat': 'neu',
        'forte': {
            'mod': '3N-3W-2-2',
            'alt': '4-2-3-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Avversario largo: centro scoperto, blocco centrale e ripartenze interne'
        },
        'pari': {
            'mod': '4-2-3-1',
            'alt': '3N-2N-1-2W-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AML': '—',
                'AMC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': 'Larghi loro: il tuo DMC e gli MC dominano il centro. Passaggi interni rapidi'
        },
        'debole': {
            'mod': '3N-2N-1-2W-2',
            'alt': '4-2-3-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Spinta esterna loro = voragine centrale: AMC e punte tra le linee'
        }
    },
    {
        'av': '4-2N-1-2W-1',
        'cat': 'neu',
        'forte': {
            'mod': '5-2-2(AML-AMR)-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Avversario largo: centro scoperto, blocco centrale e ripartenze interne'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3W-1-4-1-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Larghi loro: il tuo DMC e gli MC dominano il centro. Passaggi interni rapidi'
        },
        'debole': {
            'mod': '3W-1-4-1-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Spinta esterna loro = voragine centrale: AMC e punte tra le linee'
        }
    },
    {
        'av': '4-3W-3',
        'cat': 'neu',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Avversario largo: centro scoperto, blocco centrale e ripartenze interne'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '3-5-1-1 V',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'AML': '—',
                'MC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': 'Larghi loro: il tuo DMC e gli MC dominano il centro. Passaggi interni rapidi'
        },
        'debole': {
            'mod': '3-5-1-1 V',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Spinta esterna loro = voragine centrale: AMC e punte tra le linee'
        }
    },
    {
        'av': '4-2(DMC)-3W-1',
        'cat': 'neu',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-1-4-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Avversario largo: centro scoperto, blocco centrale e ripartenze interne'
        },
        'pari': {
            'mod': '4-1-4-1',
            'alt': '3-1-3-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Larghi loro: il tuo DMC e gli MC dominano il centro. Passaggi interni rapidi'
        },
        'debole': {
            'mod': '3-1-3-2W-1',
            'alt': '4-1-4-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Spinta esterna loro = voragine centrale: AMC e punte tra le linee'
        }
    },
    {
        'av': '4-2-3N(AMC)-1',
        'cat': 'neu',
        'forte': {
            'mod': '3W-2N-3W-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Avversario stretto al centro: compatto in mezzo, riparti sulle corsie libere'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3-1-4-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Sono stretti: le fasce sono tue. Focus Fasce e terzini che accompagnano'
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Centro intasato ma fasce vuote: dominio sulle corsie, cross e secondo palo'
        }
    },
    {
        'av': '4-2-3W-1',
        'cat': 'neu',
        'forte': {
            'mod': '5-3W-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Avversario largo: centro scoperto, blocco centrale e ripartenze interne'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3-1-3W-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Larghi loro: il tuo DMC e gli MC dominano il centro. Passaggi interni rapidi'
        },
        'debole': {
            'mod': '3-1-3W-1-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Spinta esterna loro = voragine centrale: AMC e punte tra le linee'
        }
    },
    {
        'av': '4-3N-1-2',
        'cat': 'neu',
        'forte': {
            'mod': '3-2-2-2-1 B (Butterfly)',
            'alt': '4-5-1 V-Style',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Avversario stretto al centro: compatto in mezzo, riparti sulle corsie libere. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-5-1 V-Style',
            'alt': '3-1-3N-2W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'AML': '—',
                'MC': '—',
                'AMR': '—',
                'ST': '—'
            },
            'w': 'Sono stretti: le fasce sono tue. Focus Fasce e terzini che accompagnano. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3-1-3N-2W-1',
            'alt': '4-5-1 V-Style',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Centro intasato ma fasce vuote: dominio sulle corsie, cross e secondo palo'
        }
    },
    {
        'av': '4-3W-1-2',
        'cat': 'neu',
        'forte': {
            'mod': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
            'alt': '4-1-4-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Avversario largo: centro scoperto, blocco centrale e ripartenze interne. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-1-4-1',
            'alt': '3N-1-4-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Larghi loro: il tuo DMC e gli MC dominano il centro. Passaggi interni rapidi. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3N-1-4-2',
            'alt': '4-1-4-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Spinta esterna loro = voragine centrale: AMC e punte tra le linee'
        }
    },
    {
        'av': '4-3N-2N-1',
        'cat': 'neu',
        'forte': {
            'mod': '3W-2DMC-3W-1-1 ML (Maple Leaf)',
            'alt': '4-1-3W-1-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'ML': '—',
                'MR': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Avversario stretto al centro: compatto in mezzo, riparti sulle corsie libere'
        },
        'pari': {
            'mod': '4-1-3W-1-1',
            'alt': '3-1-4-1-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': 'Sono stretti: le fasce sono tue. Focus Fasce e terzini che accompagnano'
        },
        'debole': {
            'mod': '3-1-4-1-1',
            'alt': '4-1-3W-1-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Centro intasato ma fasce vuote: dominio sulle corsie, cross e secondo palo'
        }
    },
    {
        'av': '4-1-2(AMC)-3',
        'cat': 'neu',
        'forte': {
            'mod': '5-1-3W-1',
            'alt': '4-1-3W-2',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'DMC': '↓',
                'ML': '↑',
                'MC': '↑',
                'MR': '↑',
                'ST': '—'
            },
            'w': "Avversario piu' forte: blocco ordinato, zona, e contropiede sulle fasce"
        },
        'pari': {
            'mod': '4-1-3W-2',
            'alt': '3-1-4-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': "Equilibrio: vinci i duelli a centrocampo e sfrutta l'ampiezza"
        },
        'debole': {
            'mod': '3-1-4-2',
            'alt': '4-1-3W-2',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': 'Sei superiore: pressing alto, possesso e ampiezza per allargare le maglie'
        }
    },
    {
        'av': '5-1-3N-1',
        'cat': 'dif',
        'forte': {
            'mod': '3N-3W-3W-1',
            'alt': '4-1-3-1-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Linea a 5 e blocco basso: non sfondare al centro. Blocco anche tu e riparti sulle fasce'
        },
        'pari': {
            'mod': '4-1-3-1-1',
            'alt': '3N-5-2 V',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': 'Bus avversario: pazienza, ampiezza e cross. ML/MR larghi, niente fretta'
        },
        'debole': {
            'mod': '3N-5-2 V',
            'alt': '4-1-3-1-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 dietro ma statici: pressing alto, cross continui e palle inattive'
        }
    },
    {
        'av': '5-1-3W-1',
        'cat': 'dif',
        'forte': {
            'mod': '3N-2W-3W-2',
            'alt': '4-5-1 F (Flat)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Linea a 5 e blocco basso: non sfondare al centro. Blocco anche tu e riparti sulle fasce'
        },
        'pari': {
            'mod': '4-5-1 F (Flat)',
            'alt': '3N-5-2 V',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Bus avversario: pazienza, ampiezza e cross. ML/MR larghi, niente fretta'
        },
        'debole': {
            'mod': '3N-5-2 V',
            'alt': '4-5-1 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 dietro ma statici: pressing alto, cross continui e palle inattive'
        }
    },
    {
        'av': '5-1-2N-1-1',
        'cat': 'dif',
        'forte': {
            'mod': '3N-2W-2N-2W-1',
            'alt': '4-1-3-2',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Linea a 5 e blocco basso: non sfondare al centro. Blocco anche tu e riparti sulle fasce. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-1-3-2',
            'alt': '3N-5-2 V',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'ST': '—'
            },
            'w': 'Bus avversario: pazienza, ampiezza e cross. ML/MR larghi, niente fretta. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3N-5-2 V',
            'alt': '4-1-3-2',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 dietro ma statici: pressing alto, cross continui e palle inattive'
        }
    },
    {
        'av': '5-1-2W-1-1',
        'cat': 'dif',
        'forte': {
            'mod': '3N-2W-2N-2W-1',
            'alt': '4-1-3-2',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'MC': '—',
                'AML': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Linea a 5 e blocco basso: non sfondare al centro. Blocco anche tu e riparti sulle fasce. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-1-3-2',
            'alt': '3N-5-2 V',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'DMC': '↓',
                'MC': '—',
                'ST': '—'
            },
            'w': 'Bus avversario: pazienza, ampiezza e cross. ML/MR larghi, niente fretta. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3N-5-2 V',
            'alt': '4-1-3-2',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': '5 dietro ma statici: pressing alto, cross continui e palle inattive'
        }
    },
    {
        'av': '5-2-2W-1',
        'cat': 'dif',
        'forte': {
            'mod': '3N-2W-3N-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'ML': '—',
                'MR': '—',
                'AMC': '↑',
                'ST': '—'
            },
            'w': 'Linea a 5 e blocco basso: non sfondare al centro. Blocco anche tu e riparti sulle fasce'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3W-1-2-3W-1',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Bus avversario: pazienza, ampiezza e cross. ML/MR larghi, niente fretta'
        },
        'debole': {
            'mod': '3W-1-2-3W-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'MC': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': '5 dietro ma statici: pressing alto, cross continui e palle inattive'
        }
    },
    {
        'av': '5-2-2N-1',
        'cat': 'dif',
        'forte': {
            'mod': '3W-2-3W-2',
            'alt': '4-2-2-1-1',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Linea a 5 e blocco basso: non sfondare al centro. Blocco anche tu e riparti sulle fasce'
        },
        'pari': {
            'mod': '4-2-2-1-1',
            'alt': '3N-1-3W-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'MC': '—',
                'AMC': '—',
                'ST': '—'
            },
            'w': 'Bus avversario: pazienza, ampiezza e cross. ML/MR larghi, niente fretta'
        },
        'debole': {
            'mod': '3N-1-3W-1-2',
            'alt': '4-2-2-1-1',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'DMC': '—',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': '5 dietro ma statici: pressing alto, cross continui e palle inattive'
        }
    },
    {
        'av': '3N-2W-3N-2',
        'cat': 'dif',
        'forte': {
            'mod': '5-4-1 F (Flat)',
            'alt': '4-5-1 F (Flat)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '↓',
                'DC': '↓',
                'DR': '↓',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono'
        },
        'pari': {
            'mod': '4-5-1 F (Flat)',
            'alt': '3-5-2 F (Flat)',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti'
        },
        'debole': {
            'mod': '3-5-2 F (Flat)',
            'alt': '4-5-1 F (Flat)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
        }
    },
    {
        'av': '3N-2W-2-1-2',
        'cat': 'dif',
        'forte': {
            'mod': '3W-3N-3W-1',
            'alt': '4-4-2 C (Classic)',
            'men': 'Difensiva',
            'pass': 'Fasce',
            'stile': 'Lunghi',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Easy',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DC': '↓',
                'MC': '—',
                'AML': '↑',
                'AMC': '↑',
                'AMR': '↑',
                'ST': '—'
            },
            'w': 'Difesa a 3: proteggi le fasce dove spingono, riparti largo dove non coprono. Il DMC marca il loro AMC'
        },
        'pari': {
            'mod': '4-4-2 C (Classic)',
            'alt': '3-4-1-2',
            'men': 'Normale',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'SI',
            'press': 'Basso',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'NO',
            'fr': {
                'DL': '—',
                'DC': '↓',
                'DR': '—',
                'ML': '—',
                'MC': '—',
                'MR': '—',
                'ST': '—'
            },
            'w': '3 dietro = ampiezza scoperta: ML/MR o ali al 1v1 contro i braccetti. DMC freccia blu sul loro AMC'
        },
        'debole': {
            'mod': '3-4-1-2',
            'alt': '4-4-2 C (Classic)',
            'men': 'Offensiva',
            'pass': 'Fasce',
            'stile': 'Misti',
            'ctrl': 'NO',
            'press': 'Alto',
            'cont': 'Norm',
            'marc': 'Zona',
            'fuo': 'SI',
            'fr': {
                'DC': '↓',
                'ML': '↑',
                'MC': '—',
                'MR': '↑',
                'AMC': '↑',
                'ST': '—'
            },
            'w': "Solo 3 dietro: attacca l'ampiezza con due ali larghe, cross e inserimenti"
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

# ==================== COUNTER QUICK REFERENCE ====================
# Riferimento rapido: avversario -> 3 contromoduli (per mentalita offensiva/neutra/difensiva)
# Fonte: GamingOnPhone Top Eleven Counter Formations Complete Guide

COUNTER_QUICK = [
    {
        'av': '3N-5-2 F',
        'cat': 'att',
        'off': '3-1-4-2',
        'neu': '4-3N-2W-1',
        'dif': '4-2-3-1'
    },
    {
        'av': '3W-5-2 F',
        'cat': 'att',
        'off': '3-1-3N-2W-1',
        'neu': '4-5-1 V-Style',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '3N-5-1-1',
        'cat': 'att',
        'off': '3-1-3N-1-2',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '3N-2W-2N-1-2'
    },
    {
        'av': '3W-5-1-1',
        'cat': 'att',
        'off': '3-1-3N-2W-1',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '3N-2W-2N-1-2'
    },
    {
        'av': '3W-4-3',
        'cat': 'att',
        'off': '3-5-2 V (V-Style)',
        'neu': '4-2-2-2 H (Hexagon)',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '3N-4-3',
        'cat': 'att',
        'off': '3-5-2 F (Flat)',
        'neu': '4-4-2 C (Classic)',
        'dif': '5-4-1 F (Flat)'
    },
    {
        'av': '3W-1-4-2',
        'cat': 'att',
        'off': '3-4-1-2',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '4-1-2-1-2 ND (Narrow Diamond)'
    },
    {
        'av': '3W-1-4-1-1',
        'cat': 'att',
        'off': '3-5-2 V (V-Style)',
        'neu': '4-5-1 V-Style',
        'dif': '3-5-2 V (V-Style)'
    },
    {
        'av': '3N-1-4-2',
        'cat': 'att',
        'off': '3-5-1-1 V',
        'neu': '4-5-1 V-Style',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '3N-5-2 V',
        'cat': 'att',
        'off': '3-1-3N-3',
        'neu': '4-3N-2W-1',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-5-2 V',
        'cat': 'att',
        'off': '3-1-3N-1-2',
        'neu': '4-2-2-2 H (Hexagon)',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-2N-3W-2',
        'cat': 'att',
        'off': '3W-5-2 F',
        'neu': '4-4-2 C (Classic)',
        'dif': '5-4-1 F (Flat)'
    },
    {
        'av': '3N-2(DMC/MC)-3W-2',
        'cat': 'att',
        'off': '3-1-4-2',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-2(DMC/MC)-3W-2',
        'cat': 'att',
        'off': '3-1-4-2',
        'neu': '4-4-2 C (Classic)',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3N-3(DMC/MC)-2W-2',
        'cat': 'att',
        'off': '3-1-3N-2W-1',
        'neu': '4-3N-2W-1',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-2DMC-3W-1-1 ML (Maple Leaf)',
        'cat': 'att',
        'off': '3N-1-4-2',
        'neu': '4-5-1 V-Style',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-2N-2W-1-2',
        'cat': 'att',
        'off': '3W-5-2 V',
        'neu': '4-5-1 V-Style',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-2N-2N-2W-1',
        'cat': 'att',
        'off': '3-4-1-2',
        'neu': '4-4-2 C (Classic)',
        'dif': '3N-2W-3N-2'
    },
    {
        'av': '3N-2N-1-2W-2',
        'cat': 'att',
        'off': '3-1-3W-1-2',
        'neu': '4-4-2 C (Classic)',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3N-1-2-1-3',
        'cat': 'att',
        'off': '4-3-3',
        'neu': '3-1-3N-1-2',
        'dif': '5-4-1 F (Flat)'
    },
    {
        'av': '3W-1-5-1',
        'cat': 'att',
        'off': '3-3N-3W-1',
        'neu': '4-3N-2W-1',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-1-3W-2N-1',
        'cat': 'att',
        'off': '3-5-2 V (V-Style)',
        'neu': '4-5-1 V-Style',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3N-1-3W-2N-1',
        'cat': 'att',
        'off': '3-5-1-1 V',
        'neu': '4-5-1 V-Style',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '3W-1-3W-1-2',
        'cat': 'att',
        'off': '3N-5-2 F',
        'neu': '4-4-2 C (Classic)',
        'dif': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'
    },
    {
        'av': '3N-1-3W-1-2 D (Dandelion)',
        'cat': 'att',
        'off': '3-5-1-1 V',
        'neu': '4-4-2 C (Classic)',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '3N-1-4-1-1',
        'cat': 'att',
        'off': '3-1-4-1-1',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '3W-1-3N-1-2',
        'cat': 'att',
        'off': '3-4-3',
        'neu': '3-5-2 V (V-Style)',
        'dif': '4-1-4-1'
    },
    {
        'av': '3N-4-1-2',
        'cat': 'att',
        'off': '3-1-3N-2W-1',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '3N-2W-2N-1-2'
    },
    {
        'av': '3W-4-1-2',
        'cat': 'att',
        'off': '3-1-3N-1-2',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '3N-2W-2N-1-2'
    },
    {
        'av': '4-5-1 F (Flat)',
        'cat': 'neu',
        'off': '3-5-2 F (Flat)',
        'neu': '3-5-2 V (V-Style)',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-5-1 V-Style',
        'cat': 'neu',
        'off': '3-4-3',
        'neu': '4-3N-3',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-4-2 C (Classic)',
        'cat': 'neu',
        'off': '4-1-2-1-2 ND (Narrow Diamond)',
        'neu': '4-1-2-1-2 ND (Narrow Diamond)',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '4-1(DMC)-2-3',
        'cat': 'neu',
        'off': '3-1-4-2',
        'neu': '4-1-4-1',
        'dif': '5-3N-2'
    },
    {
        'av': '4-1-2-1-2 ND (Narrow Diamond)',
        'cat': 'neu',
        'off': '3N-5-2 V',
        'neu': '3N-5-2 V',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '4-1-2-1-2 WD (Wide Diamond)',
        'cat': 'neu',
        'off': '3-4-3',
        'neu': '4-3W-1-2',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-1-2-2-1',
        'cat': 'neu',
        'off': '3-4-3',
        'neu': '4-2-2-2 H (Hexagon)',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-1-1-2W-2',
        'cat': 'neu',
        'off': '3N-2N-1-2W-2',
        'neu': '4-2-3-1',
        'dif': '3N-3W-2-2'
    },
    {
        'av': '4-1-1-2N-2',
        'cat': 'neu',
        'off': '3-4-3',
        'neu': '3W-2N-1-3W-1',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-2N-1-2N-1',
        'cat': 'neu',
        'off': '3-4-3',
        'neu': '3N-1-4-1-1',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-2N-1-2W-1',
        'cat': 'neu',
        'off': '3W-1-4-1-1',
        'neu': '4-4-2 C (Classic)',
        'dif': '5-2-2(AML-AMR)-1'
    },
    {
        'av': '4-3W-3',
        'cat': 'neu',
        'off': '3-5-1-1 V',
        'neu': '4-5-1 V-Style',
        'dif': '5-4-1 F (Flat)'
    },
    {
        'av': '4-3N-3',
        'cat': 'neu',
        'off': '3-4-3',
        'neu': '3-4-1-2',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-1-3N-2',
        'cat': 'neu',
        'off': '3-4-3',
        'neu': '3-1-3N-2W-1',
        'dif': '4-1-4-1'
    },
    {
        'av': '4-1-3N-1-1',
        'cat': 'neu',
        'off': '3-1-4-2',
        'neu': '3-1-4-1-1',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '4-1-3W-2',
        'cat': 'neu',
        'off': '3-1-4-2',
        'neu': '4-5-1 V-Style',
        'dif': '5-4-1 F (Flat)'
    },
    {
        'av': '4-1-3W-1-1',
        'cat': 'neu',
        'off': '3-1-4-1-1',
        'neu': '4-4-1-1',
        'dif': '5-1DMC-2-2'
    },
    {
        'av': '4-2(DMC)-3W-1',
        'cat': 'neu',
        'off': '3-1-3-2W-1',
        'neu': '4-1-4-1',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '4-2-3N(AMC)-1',
        'cat': 'neu',
        'off': '3-1-4-2',
        'neu': '4-4-2 C (Classic)',
        'dif': '3W-2N-3W-2'
    },
    {
        'av': '4-2-3W-1',
        'cat': 'neu',
        'off': '3-1-3W-1-2',
        'neu': '4-4-2 C (Classic)',
        'dif': '5-3W-2'
    },
    {
        'av': '4-3N-1-2',
        'cat': 'neu',
        'off': '3-1-3N-2W-1',
        'neu': '4-5-1 V-Style',
        'dif': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'av': '4-3W-1-2',
        'cat': 'neu',
        'off': '3N-1-4-2',
        'neu': '4-1-4-1',
        'dif': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'
    },
    {
        'av': '4-3-2-1 XT (Xmas Tree)',
        'cat': 'neu',
        'off': '3-1-5-1 AMC',
        'neu': '3-1-5-1 AMC',
        'dif': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'
    },
    {
        'av': '4-3N-2N-1',
        'cat': 'neu',
        'off': '3-1-4-1-1',
        'neu': '4-1-3W-1-1',
        'dif': '3W-2DMC-3W-1-1 ML (Maple Leaf)'
    },
    {
        'av': '4-3N-2W-1',
        'cat': 'neu',
        'off': '3-1-4-1-1',
        'neu': '3-1-4-1-1',
        'dif': '4-4-1-1'
    },
    {
        'av': '4-2-2-2 H (Hexagon)',
        'cat': 'neu',
        'off': '3N-4-3',
        'neu': '3N-4-1-2',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '4-1-2(AMC)-3',
        'cat': 'neu',
        'off': '3-1-4-2',
        'neu': '4-1-3W-2',
        'dif': '5-1-3W-1'
    },
    {
        'av': '4-2-1-3',
        'cat': 'neu',
        'off': '4-3-3',
        'neu': '3-1-3N-2W-1',
        'dif': '5-4-1 F (Flat)'
    },
    {
        'av': '4-1-4-1',
        'cat': 'neu',
        'off': '3-5-2 V (V-Style)',
        'neu': '4-2-2-2 H (Hexagon)',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '4-4-1-1',
        'cat': 'neu',
        'off': '3-5-2 F (Flat)',
        'neu': '3-5-2 F (Flat)',
        'dif': '4-5-1 V-Style'
    },
    {
        'av': '5-4-1 F (Flat)',
        'cat': 'dif',
        'off': '3-5-2 F (Flat)',
        'neu': '4-4-2 C (Classic)',
        'dif': '4-3N-2W-1'
    },
    {
        'av': '5-3N-2',
        'cat': 'dif',
        'off': '3N-4-1-2',
        'neu': '3N-4-1-2',
        'dif': '4-4-2 C (Classic)'
    },
    {
        'av': '5-3W-2',
        'cat': 'dif',
        'off': '3N-5-2 V',
        'neu': '3N-4-1-2',
        'dif': '4-4-2 C (Classic)'
    },
    {
        'av': '5-1-3N-1',
        'cat': 'dif',
        'off': '3N-5-2 V',
        'neu': '4-1-3-1-1',
        'dif': '3N-3W-3W-1'
    },
    {
        'av': '5-1-3W-1',
        'cat': 'dif',
        'off': '3N-5-2 V',
        'neu': '4-5-1 F (Flat)',
        'dif': '3N-2W-3W-2'
    },
    {
        'av': '5-1-2N-1-1',
        'cat': 'dif',
        'off': '3N-5-2 V',
        'neu': '4-1-3-2',
        'dif': '3N-2W-2N-2W-1'
    },
    {
        'av': '5-1-2W-1-1',
        'cat': 'dif',
        'off': '3N-5-2 V',
        'neu': '4-1-3-2',
        'dif': '3N-2W-2N-2W-1'
    },
    {
        'av': '5-2-2W-1',
        'cat': 'dif',
        'off': '3W-1-2-3W-1',
        'neu': '4-4-2 C (Classic)',
        'dif': '3N-2W-3N-2'
    },
    {
        'av': '5-2W-2N-1',
        'cat': 'dif',
        'off': '4-3-3',
        'neu': '3N-1-3W-1-2',
        'dif': '4-4-2 C (Classic)'
    },
    {
        'av': '5-2-2N-1',
        'cat': 'dif',
        'off': '3N-1-3W-1-2',
        'neu': '4-2-2-1-1',
        'dif': '3W-2-3W-2'
    },
    {
        'av': '5-2-1-2 X (X-Style)',
        'cat': 'dif',
        'off': '3N-1-4-2',
        'neu': '3N-1-4-2',
        'dif': '4-1-2N-1-2'
    },
    {
        'av': '5-1-1-1-2',
        'cat': 'dif',
        'off': '4-3-3',
        'neu': '3N-5-2 V',
        'dif': '4-4-2 C (Classic)'
    },
    {
        'av': '3N-2W-3N-2',
        'cat': 'dif',
        'off': '3-5-2 F (Flat)',
        'neu': '4-5-1 F (Flat)',
        'dif': '5-4-1 F (Flat)'
    },
    {
        'av': '3N-2W-2-1-2',
        'cat': 'dif',
        'off': '3-4-1-2',
        'neu': '4-4-2 C (Classic)',
        'dif': '3W-3N-3W-1'
    },
    {
        'av': '3-2-2-2-1 B (Butterfly)',
        'cat': 'dif',
        'off': '4-3-3',
        'neu': '3-4-1-2',
        'dif': '5-4-1 F (Flat)'
    }
]


# ==================== MATCHUP MATRIX ====================
# Matrice avversario -> counter consigliato per ogni stile di gioco (offensivo/neutro/difensivo)

MATCHUP_MATRIX = [
    {
        'opponent': '3N-5-2 F',
        'category': 'att',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-3N-2W-1',
        'counter_defensive': '4-2-3-1'
    },
    {
        'opponent': '3W-5-2 F',
        'category': 'att',
        'counter_offensive': '3-1-3N-2W-1',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '3N-4-3',
        'category': 'att',
        'counter_offensive': '3-5-2 F (Flat)',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3W-4-3',
        'category': 'att',
        'counter_offensive': '3-5-2 V (V-Style)',
        'counter_neutral': '4-2-2-2 H (Hexagon)',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '3W-1-4-2',
        'category': 'att',
        'counter_offensive': '3-4-1-2',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '4-1-2-1-2 ND (Narrow Diamond)'
    },
    {
        'opponent': '3N-1-4-2',
        'category': 'att',
        'counter_offensive': '3-5-1-1 V',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '3N-5-2 V',
        'category': 'att',
        'counter_offensive': '3-1-3N-3',
        'counter_neutral': '4-3N-2W-1',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3N-1-3W-1-2 D (Dandelion)',
        'category': 'att',
        'counter_offensive': '3-5-1-1 V',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '3N-2-2-2-1 B (Butterfly 3N)',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-2-2-2 H (Hexagon)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3W-2DMC-3W-1-1 ML (Maple Leaf)',
        'category': 'att',
        'counter_offensive': '3N-1-4-2',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '4-4-2 C (Classic)',
        'category': 'neu',
        'counter_offensive': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '4-5-1 V-Style',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-3N-3',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '4-5-1 F (Flat)',
        'category': 'neu',
        'counter_offensive': '3-5-2 F (Flat)',
        'counter_neutral': '3-5-2 V (V-Style)',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '4-1-2-1-2 ND (Narrow Diamond)',
        'category': 'neu',
        'counter_offensive': '3N-5-2 V',
        'counter_neutral': '3N-5-2 V',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '4-2-2-2 H (Hexagon)',
        'category': 'neu',
        'counter_offensive': '3N-4-3',
        'counter_neutral': '3N-4-1-2',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '4-3N-2W-1',
        'category': 'neu',
        'counter_offensive': '3-1-4-1-1',
        'counter_neutral': '3-1-4-1-1',
        'counter_defensive': '4-4-1-1'
    },
    {
        'opponent': '4-1-4-1',
        'category': 'neu',
        'counter_offensive': '3-5-2 V (V-Style)',
        'counter_neutral': '4-2-2-2 H (Hexagon)',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '4-4-1-1',
        'category': 'neu',
        'counter_offensive': '3-5-2 F (Flat)',
        'counter_neutral': '3-5-2 F (Flat)',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '4-2-3-1',
        'category': 'neu',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-1-4-1',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3-4-1-2',
        'category': 'neu',
        'counter_offensive': '3-5-2 F (Flat)',
        'counter_neutral': '4-1-3W-1-1',
        'counter_defensive': '4-1-2-1-2 ND (Narrow Diamond)'
    },
    {
        'opponent': '3N-1-4-1-1',
        'category': 'att',
        'counter_offensive': '3-1-4-1-1',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '3W-1-4-1-1',
        'category': 'att',
        'counter_offensive': '3-5-2 V (V-Style)',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '3-5-2 V (V-Style)'
    },
    {
        'opponent': '4-1-3N-1-1',
        'category': 'neu',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '3-1-4-1-1',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '4-1-3W-1-1',
        'category': 'neu',
        'counter_offensive': '3-1-4-1-1',
        'counter_neutral': '4-4-1-1',
        'counter_defensive': '5-1DMC-2-2'
    },
    {
        'opponent': '3-1-3-2-1 (Tiki-taka)',
        'category': 'att',
        'counter_offensive': '4-3N-3',
        'counter_neutral': '4-3N-2W-1',
        'counter_defensive': '4-5-1 V-Style'
    },
    {
        'opponent': '3-1-3-1-2',
        'category': 'att',
        'counter_offensive': '3-5-2 V (V-Style)',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '3-5-2 F (Flat)'
    },
    {
        'opponent': '5-4-1 F (Flat)',
        'category': 'dif',
        'counter_offensive': '3-5-2 F (Flat)',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '4-3N-2W-1'
    },
    {
        'opponent': '5-3N-2',
        'category': 'dif',
        'counter_offensive': '3N-4-1-2',
        'counter_neutral': '3N-4-1-2',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '5-3W-2',
        'category': 'dif',
        'counter_offensive': '3N-5-2 V',
        'counter_neutral': '3N-4-1-2',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '5-2-1-2 X (X-Style)',
        'category': 'dif',
        'counter_offensive': '3N-1-4-2',
        'counter_neutral': '3N-1-4-2',
        'counter_defensive': '4-1-2N-1-2'
    },
    {
        'opponent': '3-1-5-1 AMC',
        'category': 'neu',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-2-3-1',
        'counter_defensive': '4-3-3'
    },
    {
        'opponent': '4-3-3',
        'category': 'neu',
        'counter_offensive': '4-1-3-2',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '5-2-2(AML-AMR)-1',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3W-1-2-3W-1'
    },
    {
        'opponent': '4-1-3W-2',
        'category': 'neu',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3-1-4-2',
        'category': 'att',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '5-3W-2'
    },
    {
        'opponent': '3W-2N-3N-2',
        'category': 'dif',
        'counter_offensive': '3-5-2 F (Flat)',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3-5-2 F (Flat)',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-3N-2W-1',
        'counter_defensive': '5-3-2'
    },
    {
        'opponent': '3-5-2 V (V-Style)',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-2-2-2 H (Hexagon)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3-4-3',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-2-2-2 H (Hexagon)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)',
        'category': 'att',
        'counter_offensive': '4-4-2 C (Classic)',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '5-1DMC-2-2',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-1-3W-1-1',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '4-1-3-1W-1',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-1-3-1-1',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '3-1-4-1-1',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-1-2-2-1',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-2-2-2 H (Hexagon)',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': 'False Nine + Wingers',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-1-3-1-1',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-2-4',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '5-4-1 F (Flat)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-1-3-1-1',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '4-3-2-1 XT (Xmas Tree)',
        'category': 'neu',
        'counter_offensive': '3-1-5-1 AMC',
        'counter_neutral': '3-1-5-1 AMC',
        'counter_defensive': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'
    },
    {
        'opponent': '5-3-2',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '3-1-3-2W-1',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-1-4-1',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3-3-1-3',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-1-4-1',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-2-2-1-1',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '4-1-1-3-1',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-3-1-2',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '3-1-2-1-3',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-1-3-1-1',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3-4-2-1',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-3-3',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '5-2-3',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-3-3',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '4-2-2-2 N (Narrow)',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-3-3',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '3-1-4-2 W',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-2-3-1',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-2-3-1 Attack',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '4-1-3N-2',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-2-3-1-2',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-3-3',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '4-1-2-1-2 WD (Wide Diamond)',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '4-3W-1-2',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '3-2-2-2-1 B (Butterfly)',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '3-4-1-2',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-1-3N-2',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '3-1-3N-2W-1',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '4-3N-3',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '3-4-1-2',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '3N-1-2-1-3',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '3-1-3N-1-2',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-2-1-3',
        'category': 'att',
        'counter_offensive': '4-3-3',
        'counter_neutral': '3-1-3N-2W-1',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-1-1-2N-2',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '3W-2N-1-3W-1',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '3W-1-3N-1-2',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '3-5-2 V (V-Style)',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '4-2N-1-2N-1',
        'category': 'neu',
        'counter_offensive': '3-4-3',
        'counter_neutral': '3N-1-4-1-1',
        'counter_defensive': '4-1-4-1'
    },
    {
        'opponent': '5-1-1-1-2',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '3N-5-2 V',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '5-2W-2N-1',
        'category': 'dif',
        'counter_offensive': '4-3-3',
        'counter_neutral': '3N-1-3W-1-2',
        'counter_defensive': '4-4-2 C (Classic)'
    },
    {
        'opponent': '3N-5-1-1',
        'category': 'att',
        'counter_offensive': '3-1-3N-1-2',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '3N-2W-2N-1-2'
    },
    {
        'opponent': '3W-5-1-1',
        'category': 'att',
        'counter_offensive': '3-1-3N-2W-1',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '3N-2W-2N-1-2'
    },
    {
        'opponent': '3W-5-2 V',
        'category': 'att',
        'counter_offensive': '3-1-3N-1-2',
        'counter_neutral': '4-2-2-2 H (Hexagon)',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3W-2N-3W-2',
        'category': 'att',
        'counter_offensive': '3W-5-2 F',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3N-2(DMC/MC)-3W-2',
        'category': 'att',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3W-2(DMC/MC)-3W-2',
        'category': 'att',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3N-3(DMC/MC)-2W-2',
        'category': 'att',
        'counter_offensive': '3-1-3N-2W-1',
        'counter_neutral': '4-3N-2W-1',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3W-2N-2W-1-2',
        'category': 'att',
        'counter_offensive': '3W-5-2 V',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3W-2N-2N-2W-1',
        'category': 'att',
        'counter_offensive': '3-4-1-2',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3N-2W-3N-2'
    },
    {
        'opponent': '3N-2N-1-2W-2',
        'category': 'att',
        'counter_offensive': '3-1-3W-1-2',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3W-1-5-1',
        'category': 'att',
        'counter_offensive': '3-3N-3W-1',
        'counter_neutral': '4-3N-2W-1',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3W-1-3W-2N-1',
        'category': 'att',
        'counter_offensive': '3-5-2 V (V-Style)',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3N-1-3W-2N-1',
        'category': 'att',
        'counter_offensive': '3-5-1-1 V',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '3W-1-3W-1-2',
        'category': 'att',
        'counter_offensive': '3N-5-2 F',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'
    },
    {
        'opponent': '3N-4-1-2',
        'category': 'att',
        'counter_offensive': '3-1-3N-2W-1',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '3N-2W-2N-1-2'
    },
    {
        'opponent': '3W-4-1-2',
        'category': 'att',
        'counter_offensive': '3-1-3N-1-2',
        'counter_neutral': '4-1-2-1-2 ND (Narrow Diamond)',
        'counter_defensive': '3N-2W-2N-1-2'
    },
    {
        'opponent': '4-1(DMC)-2-3',
        'category': 'neu',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-1-4-1',
        'counter_defensive': '5-3N-2'
    },
    {
        'opponent': '4-1-1-2W-2',
        'category': 'neu',
        'counter_offensive': '3N-2N-1-2W-2',
        'counter_neutral': '4-2-3-1',
        'counter_defensive': '3N-3W-2-2'
    },
    {
        'opponent': '4-2N-1-2W-1',
        'category': 'neu',
        'counter_offensive': '3W-1-4-1-1',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '5-2-2(AML-AMR)-1'
    },
    {
        'opponent': '4-3W-3',
        'category': 'neu',
        'counter_offensive': '3-5-1-1 V',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '4-2(DMC)-3W-1',
        'category': 'neu',
        'counter_offensive': '3-1-3-2W-1',
        'counter_neutral': '4-1-4-1',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '4-2-3N(AMC)-1',
        'category': 'neu',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3W-2N-3W-2'
    },
    {
        'opponent': '4-2-3W-1',
        'category': 'neu',
        'counter_offensive': '3-1-3W-1-2',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '5-3W-2'
    },
    {
        'opponent': '4-3N-1-2',
        'category': 'neu',
        'counter_offensive': '3-1-3N-2W-1',
        'counter_neutral': '4-5-1 V-Style',
        'counter_defensive': '3-2-2-2-1 B (Butterfly)'
    },
    {
        'opponent': '4-3W-1-2',
        'category': 'neu',
        'counter_offensive': '3N-1-4-2',
        'counter_neutral': '4-1-4-1',
        'counter_defensive': '3W-2DMC-3N-1-1 Tower (Eiffel Tower)'
    },
    {
        'opponent': '4-3N-2N-1',
        'category': 'neu',
        'counter_offensive': '3-1-4-1-1',
        'counter_neutral': '4-1-3W-1-1',
        'counter_defensive': '3W-2DMC-3W-1-1 ML (Maple Leaf)'
    },
    {
        'opponent': '4-1-2(AMC)-3',
        'category': 'neu',
        'counter_offensive': '3-1-4-2',
        'counter_neutral': '4-1-3W-2',
        'counter_defensive': '5-1-3W-1'
    },
    {
        'opponent': '5-1-3N-1',
        'category': 'dif',
        'counter_offensive': '3N-5-2 V',
        'counter_neutral': '4-1-3-1-1',
        'counter_defensive': '3N-3W-3W-1'
    },
    {
        'opponent': '5-1-3W-1',
        'category': 'dif',
        'counter_offensive': '3N-5-2 V',
        'counter_neutral': '4-5-1 F (Flat)',
        'counter_defensive': '3N-2W-3W-2'
    },
    {
        'opponent': '5-1-2N-1-1',
        'category': 'dif',
        'counter_offensive': '3N-5-2 V',
        'counter_neutral': '4-1-3-2',
        'counter_defensive': '3N-2W-2N-2W-1'
    },
    {
        'opponent': '5-1-2W-1-1',
        'category': 'dif',
        'counter_offensive': '3N-5-2 V',
        'counter_neutral': '4-1-3-2',
        'counter_defensive': '3N-2W-2N-2W-1'
    },
    {
        'opponent': '5-2-2W-1',
        'category': 'dif',
        'counter_offensive': '3W-1-2-3W-1',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3N-2W-3N-2'
    },
    {
        'opponent': '5-2-2N-1',
        'category': 'dif',
        'counter_offensive': '3N-1-3W-1-2',
        'counter_neutral': '4-2-2-1-1',
        'counter_defensive': '3W-2-3W-2'
    },
    {
        'opponent': '3N-2W-3N-2',
        'category': 'dif',
        'counter_offensive': '3-5-2 F (Flat)',
        'counter_neutral': '4-5-1 F (Flat)',
        'counter_defensive': '5-4-1 F (Flat)'
    },
    {
        'opponent': '3N-2W-2-1-2',
        'category': 'dif',
        'counter_offensive': '3-4-1-2',
        'counter_neutral': '4-4-2 C (Classic)',
        'counter_defensive': '3W-3N-3W-1'
    }
]


# ==================== CAREER PATHS ====================
# Percorsi tattici consigliati per livello stelle rosa (3, 4, 5, 6, 7+)

CAREER_PATHS = [
    {
        "id": 'starter-3',
        "stars": 3,
        "label": '3★',
        "title_en": 'Starter: 3★ rookie squad',
        "title_it": 'Esordi: rosa rookie da 3 stelle',
        "subtitle_en": 'Your first season - building the foundation',
        "subtitle_it": 'Prima stagione - costruisci le fondamenta',
        "expected_outcome_en": 'Mid-table finish, league safety, 1 free 6★ from the youth academy',
        "expected_outcome_it": "Salvezza tranquilla a metà classifica, 1 giovane da 6 stelle gratis dall'accademia",
        "recommended_formations": ['4-4-2 C (Classic)', '5-4-1 F (Flat)', '4-5-1 V-Style'],
        "explanation_en": 'With a 3★ squad you cannot dictate matches: defend smart and grab points. The 4-4-2 Classic is the simplest tactical management; the 5-4-1 saves you against stronger sides; the 4-5-1 V-Style lets you steal wins on the counter.',
        "explanation_it": 'Con una rosa da 3 stelle non puoi dettare le partite: difendi con criterio e prendi i punti. Il 4-4-2 Classico è la gestione tattica più semplice; il 5-4-1 ti salva contro i più forti; il 4-5-1 V-Style ti permette di rubare partite in contropiede.',
        "training_priority_en": ['GK (clean sheets are worth more than 5★ strikers)', 'Central CBs', 'Stamina across the whole team'],
        "training_priority_it": ['GK (i clean sheet valgono più di un attaccante da 5 stelle)', 'DC centrali', 'Resistenza per tutta la squadra'],
        "avoid_en": ["3-back formations (your CBs aren't ready)", "High pressing (burns stamina you don't have)", 'Offering 30+ tokens at auctions'],
        "avoid_it": ['Formazioni a 3 difensori (i tuoi DC non sono pronti)', 'Pressing alto (brucia stamina che non hai)', 'Offerte oltre 30 token alle aste']
    },
    {
        "id": 'growing-4',
        "stars": 4,
        "label": '4★',
        "title_en": 'Growing: 4★ ambitious squad',
        "title_it": 'Crescita: rosa ambiziosa da 4 stelle',
        "subtitle_en": 'Champions League contender',
        "subtitle_it": 'In corsa per la Champions',
        "expected_outcome_en": 'Top-4 finish, semifinal in domestic cup, group-stage qualification in Champions League',
        "expected_outcome_it": 'Piazzamento Champions, semifinale di coppa nazionale, qualificazione gironi in Champions League',
        "recommended_formations": ['4-3-3', '4-2-3-1', '4-4-2 C (Classic)'],
        "explanation_en": 'At 4★ you can finally play. 4-3-3 is the main meta module (beats 26/56). The 4-2-3-1 gives tactical versatility. Keep the 4-4-2 as a safe option when you face the strongest opponents in cups.',
        "explanation_it": 'A 4 stelle puoi finalmente giocartela. 4-3-3 è il modulo meta principale (batte 26/56). Il 4-2-3-1 dà versatilità tattica. Tieni il 4-4-2 come piano sicuro contro i più forti in coppa.',
        "training_priority_en": ['Box-to-Box midfielders (engine room)', 'Wingers with Pace + Crossing', 'A Playmaker DMC if you want the 4-3-3 Tuned'],
        "training_priority_it": ['Centrocampisti Box-to-Box (motore)', 'Ali con Velocità + Cross', 'Un DMC Regista se vuoi il 4-3-3 Tuned'],
        "avoid_en": ['Too aggressive Monster 4-2-3-1 against equal teams', 'Buying super-strikers ignoring the central spine'],
        "avoid_it": ['Monster 4-2-3-1 troppo aggressivo contro pari livello', 'Comprare super-attaccanti trascurando la spina dorsale']
    },
    {
        "id": 'competitive-5',
        "stars": 5,
        "label": '5★',
        "title_en": 'Competitive: 5★ elite squad',
        "title_it": 'Competitivi: rosa élite da 5 stelle',
        "subtitle_en": 'Title contention and European hopes',
        "subtitle_it": "In lotta per il titolo e per l'Europa",
        "expected_outcome_en": 'League title fight, cup final, Champions League quarter-finals',
        "expected_outcome_it": 'Lotta per il titolo, finale di coppa, quarti di Champions League',
        "recommended_formations": ['4-3-3 Tuned Meta', '4-5-1 V-Style', '4-2-3-1 Vertical Tiki-Taka'],
        "explanation_en": 'At 5★ you can express the modern meta. 4-3-3 Tuned with False 9 + Playmaker DMC dominates. The 4-5-1 V-Style is the tactical chameleon. Vertical Tiki-Taka exploits possession + speed to break through tough defenses.',
        "explanation_it": 'A 5 stelle puoi esprimere il meta moderno. 4-3-3 Tuned con Falso 9 + DMC Regista domina. Il 4-5-1 V-Style è il camaleonte tattico. Il Vertical Tiki-Taka sfrutta possesso + velocità per scardinare difese chiuse.',
        "training_priority_en": ['A False 9 striker (white attributes 95+)', 'Playmaker DMC (Pirlo role)', 'Inverted wingers AML/AMR (Dual Position)'],
        "training_priority_it": ['Un Falso 9 (attributi bianchi 95+)', 'DMC Regista (ruolo Pirlo)', 'Ali invertite AML/AMR (Dual Position)'],
        "avoid_en": ['Switching shape every match (Team Balance must stay 9.2-10)', 'Forgetting the special abilities of your stars'],
        "avoid_it": ['Cambiare modulo a ogni partita (il Team Balance deve restare 9.2-10)', 'Dimenticare le abilità speciali dei tuoi top']
    },
    {
        "id": 'dominant-6',
        "stars": 6,
        "label": '6★',
        "title_en": 'Dominant: 6★ super squad',
        "title_it": 'Dominanti: super rosa da 6 stelle',
        "subtitle_en": 'Treble dreams',
        "subtitle_it": 'Sogno triplete',
        "expected_outcome_en": 'League title, domestic cup, Champions League at least semifinal (often the title)',
        "expected_outcome_it": 'Titolo di campionato, coppa nazionale, Champions League almeno semifinale (spesso vittoria)',
        "recommended_formations": ['4-3-3 Tuned Meta', '4-2-3-1 Vertical Tiki-Taka', '3-4-2-1'],
        "explanation_en": 'At 6★ you no longer fear anyone. 4-3-3 Tuned remains the king. Vertical Tiki-Taka makes you dominant in possession. 3-4-2-1 (Conte/Tuchel style) is the magic weapon in Champions League with two #10s.',
        "explanation_it": "A 6 stelle non temi più nessuno. 4-3-3 Tuned resta il re. Il Vertical Tiki-Taka ti rende dominante nel possesso. Il 3-4-2-1 (stile Conte/Tuchel) è l'arma magica in Champions con doppio trequartista.",
        "training_priority_en": ['Set Piece Master ability on the AMC', 'Aerial Threat ability on at least 2 players', 'Maximum Team Balance (9.5+)'],
        "training_priority_it": ["Abilità Set Piece Master sull'AMC", 'Abilità Aerial Threat su almeno 2 giocatori', 'Team Balance massimo (9.5+)'],
        "avoid_en": ['Resting key players too much against stronger opponents', "Overtraining single 'mutant' players that break the balance"],
        "avoid_it": ['Lasciare a riposo i top contro avversari forti', "Sovrallenare singoli 'mutanti' che spezzano l'equilibrio"]
    },
    {
        "id": 'godlike-7',
        "stars": 7,
        "label": '7★+',
        "title_en": 'Godlike: 7★+ legendary squad',
        "title_it": 'Leggenda: rosa epica da 7+ stelle',
        "subtitle_en": 'When victory is mathematics',
        "subtitle_it": 'Quando vincere è una matematica',
        "expected_outcome_en": 'Wins every competition. Goal: undefeated season',
        "expected_outcome_it": 'Vince qualsiasi competizione. Obiettivo: stagione imbattuto',
        "recommended_formations": ['4-3-3 Tuned Meta', '4-2-3-1 Monster', '3-4-3 Press'],
        "explanation_en": 'At 7★+ you can afford the Monster, which sacrifices the defense for total attacking dominance. 3-4-3 Press for gegenpressing. 4-3-3 Tuned remains the safe choice for important matches.',
        "explanation_it": 'A 7+ stelle puoi permetterti il Monster, che sacrifica la difesa per dominio totale. Il 3-4-3 Press per gegenpressing. Il 4-3-3 Tuned resta la scelta sicura per i match importanti.',
        "training_priority_en": ['Maintain Team Balance at 10/10 against all odds', 'Rotate the squad to keep morale + fitness', "Don't sell aging players too early: they still convert chances"],
        "training_priority_it": ['Tieni il Team Balance a 10/10 a tutti i costi', 'Ruota la rosa per tenere morale + condizione', 'Non vendere i veterani troppo presto: convertono ancora'],
        "avoid_en": ['Underestimating opponents', "Massive purchases that break balance (the 'mutant')", 'Playing Monster against teams of equal strength'],
        "avoid_it": ['Sottovalutare gli avversari', "Acquisti enormi che rompono il balance (il 'mutante')", 'Giocare il Monster contro pari livello']
    }
]

# ==================== MY PLAYBOOK ====================
# Playstyle personale - Tiki-Taka Possessivo (Barca 2010/11 ispirato)
# 13 categorie distinte. Solo IT popolato.

MY_PLAYBOOK = [
    {
        "id": "philosophy",
        "order": 1,
        "category_en": "Philosophy & Identity",
        "category_it": "Filosofia & Identita",
        "icon": "compass-outline",
        "summary_it": "Il possesso e una forma di difesa. Se ho la palla, l'avversario non segna. Pazienza, controllo, stancare l'avversario.",
        "summary_en": "Possession is a form of defense.",
        "bullets_it": [
            "Pazienza > fretta: 25+ passaggi per azione, vincere 1-0 al 88' va benissimo",
            "Il numero non conta: 75% possesso e 1-0 finale e' un successo",
            "Stancare l'avversario: nel secondo tempo crolla, li' decido la partita",
            "Ispirazione: Barcellona 2010/11 di Guardiola",
        ],
        "bullets_en": [],
        "table_it": None,
        "table_en": None,
    },
    {
        "id": "dna",
        "order": 2,
        "category_en": "Squad DNA",
        "category_it": "DNA della rosa",
        "icon": "people-outline",
        "summary_it": "Profilo titolari ideali per il 4-3-3 tiki-taka. Il giocatore piu' forte e' il DMC playmaker, non l'attaccante.",
        "summary_en": "",
        "bullets_it": [
            "Regola d'oro: DMC playmaker = cervello del sistema",
            "Abilita chiave: Playmaker (MC/DMC) + Shadow Striker (MC dx, inserimenti) + One-on-One Scoring (ali)",
            "False Nine = playstyle ST piu' forte del meta 2026",
            "Evitare: attaccanti tank lenti, terzini Wing-Back, AMC puro nel 4-3-3",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "GK", "value": "Sweeper Keeper - Riflessi, Uscite, Posizionamento"},
            {"label": "DC sx", "value": "Ball-Playing (Pique) - Passaggio, Marcatura, Creativita"},
            {"label": "DC dx", "value": "No-Nonsense - Contrasto, Marcatura, Forza"},
            {"label": "DL/DR", "value": "Full-Back (NO Wing-Back) - Marcatura, Velocita"},
            {"label": "DMC", "value": "Deep-Lying Playmaker (Busquets) - Passaggio, Visione"},
            {"label": "MC sx", "value": "Mezzala creativa (Xavi) - Passaggio, Creativita"},
            {"label": "MC dx", "value": "Mezzala incursore (Iniesta) - Dribbling, Creativita"},
            {"label": "AML", "value": "Inverted Winger - Dribbling, Velocita, Tiro"},
            {"label": "AMR", "value": "Inverted Winger - Dribbling, Velocita, Tiro"},
            {"label": "ST", "value": "False Nine (Messi) - Finalizzazione, Creativita, Visione"},
        ],
        "table_en": None,
    },
    {
        "id": "formations",
        "order": 3,
        "category_en": "Formation repertoire",
        "category_it": "Repertorio moduli",
        "icon": "grid-outline",
        "summary_it": "3 moduli + 1 emergenza. Mai di piu'.",
        "summary_en": "",
        "bullets_it": [
            "Non uso mai: 5-4-1 Flat (no DNA), 4-4-2 Classic (poca creativita centrale)",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Default", "value": "4-3-3 puro - vs pari/deboli (story: tiki-taka-barca)"},
            {"label": "Vs forti", "value": "3-1-5-1 AMC - pressing alto (story: tiki-taka-fanatic)"},
            {"label": "Plan B", "value": "4-1-2-1-2 ND - contro transizioni veloci"},
            {"label": "Emergenza", "value": "3-4-1-2 - solo da 0-2 (story: comeback-with-arrows)"},
        ],
        "table_en": None,
    },
    {
        "id": "setup",
        "order": 4,
        "category_en": "Base tactical setup",
        "category_it": "Setup tattico base",
        "icon": "settings-outline",
        "summary_it": "Setup del 4-3-3 default. Cambio solo per emergenze.",
        "summary_en": "",
        "bullets_it": [],
        "bullets_en": [],
        "table_it": [
            {"label": "Mentalita", "value": "Normale - tutta la partita"},
            {"label": "Passaggi", "value": "Sulle Fasce - sfrutto ali Dual Position [meta 2026]"},
            {"label": "Stile", "value": "Corto - mai lungo"},
            {"label": "Pressing", "value": "Basso - conservo condizione fisica"},
            {"label": "Marcatura", "value": "A Zona - blocco compatto"},
            {"label": "Fuorigioco", "value": "ON - difesa alta tipo Barca"},
            {"label": "Tackling", "value": "Normale - non perdo palla con duri"},
            {"label": "Counter forzato", "value": "OFF - privilegia la manovra"},
            {"label": "Gioco largo", "value": "ON - AML/AMR larghi (Dual Position Advantage)"},
        ],
        "table_en": None,
    },
    {
        "id": "arrows",
        "order": 5,
        "category_en": "Arrows & movements",
        "category_it": "Frecce & movimenti",
        "icon": "swap-vertical-outline",
        "summary_it": "Freccia DMC condizionata all'AMC avversario. Senza la freccia giusta il sistema crolla.",
        "summary_en": "",
        "bullets_it": [
            "REGOLA DMC: BLU di default (stopper avanzato, +clean sheet)",
            "DMC ROSSA solo se l'avversario NON ha AMC > DMC sale come MC aggiunto",
            "4-3-3: niente frecce su ali (gia' alte). Niente su terzini (no sovrapposizioni)",
            "3-1-5-1: BLU su DMC + ROSSA su AMC (finalizzatore reale)",
            "Vs 5-4-1 Flat: ROSSA sui due terzini",
        ],
        "bullets_en": [],
        "table_it": None,
        "table_en": None,
    },
    {
        "id": "phases",
        "order": 6,
        "category_en": "4 phases of play",
        "category_it": "Le 4 fasi di gioco",
        "icon": "git-network-outline",
        "summary_it": "Cosa deve succedere in ciascuna delle 4 fasi.",
        "summary_en": "",
        "bullets_it": [
            "A) Costruzione: 3v2 in uscita (GK+2DC vs 2 punte). DMC si abbassa se pressing a 3. Mai lanci lunghi.",
            "B) Sviluppo: triangoli MC-DMC-MC. Terzini larghi e BASSI. Ali aspettano alte.",
            "C) Finalizzazione: Falso 9 si abbassa > libera spazio per ala. Mezzala lato debole arriva in area. KPI: 25+ passaggi per azione.",
            "D) Non-possesso: regola dei 6 secondi. Pressing immediato. Se non torna in 6'', ritorno in posizione.",
        ],
        "bullets_en": [],
        "table_it": None,
        "table_en": None,
    },
    {
        "id": "scenarios",
        "order": 7,
        "category_en": "Match scenarios playbook",
        "category_it": "Playbook scenari",
        "icon": "list-outline",
        "summary_it": "Per livello stelle e per punteggio.",
        "summary_en": "",
        "bullets_it": [],
        "bullets_en": [],
        "table_it": [
            {"label": "Vs Forte (+1/+2)", "value": "3-1-5-1 AMC - Difensiva > Normale al 60'"},
            {"label": "Vs Pari", "value": "4-3-3 - Normale (default)"},
            {"label": "Vs Debole (-1)", "value": "4-3-3 - Normale > Offensiva al 60'"},
            {"label": "In vantaggio 1-0 70'+", "value": "Difensiva ma MANTENGO possesso"},
            {"label": "In svantaggio 0-1 60'+", "value": "Offensiva. NON cambio modulo"},
            {"label": "In svantaggio 0-2 60'+", "value": "Cambio al 3-4-1-2"},
            {"label": "Pareggio vs forte 80'+", "value": "Difensiva + DC freschi"},
        ],
        "table_en": None,
    },
    {
        "id": "counters",
        "order": 8,
        "category_en": "Counter to tough opponents",
        "category_it": "Counter ai moduli ostici",
        "icon": "shield-outline",
        "summary_it": "I 5 moduli che mi danno fastidio e come reagire.",
        "summary_en": "",
        "bullets_it": [],
        "bullets_en": [],
        "table_it": [
            {"label": "5-4-1 Flat (bus)", "value": "Offensiva dal 65', passaggi Fasce, freccia rossa su 1 terzino"},
            {"label": "4-2-3-1 con DMC", "value": "NO attacco centrale (DMC blocca). Sulle Fasce + modulo 4-1-3N-2"},
            {"label": "3-5-2 V", "value": "Sweeper Keeper alto, DMC si abbassa (build-up 3+1)"},
            {"label": "4-1-2-1-2 ND", "value": "Apro con ala inversa - passaggi al centro non bastano"},
            {"label": "4-3-3 specchio", "value": "Vince chi ha DMC e AMC migliori"},
        ],
        "table_en": None,
    },
    {
        "id": "subs",
        "order": 9,
        "category_en": "Substitutions",
        "category_it": "Sostituzioni standard",
        "icon": "swap-horizontal-outline",
        "summary_it": "3 sostituzioni standard nel 4-3-3.",
        "summary_en": "",
        "bullets_it": [
            "Regola: mai sostituire un difensore mentre rimonto",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "60' - MC stanco", "value": "MC fresco con Playmaker (mantengo precisione)"},
            {"label": "75' - Vinco 1-0/2-0", "value": "DMC fresco entra per 1 mezzala (chiudo)"},
            {"label": "85' - Vantaggio risicato", "value": "DC fresco per terzino offensivo (difesa a 5)"},
        ],
        "table_en": None,
    },
    {
        "id": "season",
        "order": 10,
        "category_en": "Season rhythm & tokens",
        "category_it": "Ritmo stagionale & token",
        "icon": "calendar-outline",
        "summary_it": "Settimana tipo + asta + regole token.",
        "summary_en": "",
        "bullets_it": [
            "Lun-Mer: rotazione 2 undici, allenamenti Passaggio+Creativita",
            "Gio: partita campionato, undici titolare",
            "Ven-Sab: condizione/morale, NO Allenamenti Rapidi",
            "Dom: knockout/Coppa, qui uso eventuali Rapidi",
            "Asta priorita: 1) DMC playmaker giovane 2) MC creativa under 21 3) AML/AMR dribbler piede inverso 4) DC Ball-Playing 5) ST False Nine se libero",
            "Token: 80% riservati a knockout Champions. 0 token su attaccanti puri. Prima rosa sana, poi asta.",
        ],
        "bullets_en": [],
        "table_it": None,
        "table_en": None,
    },
    {
        "id": "mistakes",
        "order": 11,
        "category_en": "Mistakes to avoid",
        "category_it": "Errori da NON fare",
        "icon": "warning-outline",
        "summary_it": "Autoregole, ognuna nata da una lezione.",
        "summary_en": "",
        "bullets_it": [
            "Mai Pressing Alto nel 1' tempo (esaurisce stamina, crolli nel finale)",
            "Mai scendere sotto Team Balance 9.2-10 ('mutante' danneggia il collettivo)",
            "Mai frecce ROSSE su giocatori con Velocita bassa",
            "Mai Offensiva dal 1' (brucio condizione)",
            "Mai cambiare modulo durante la partita (eccezione: 0-2 + rimonta)",
            "Mai Allenamento Rapido fuori da knockout",
            "Mai vendere il DMC playmaker, neanche al triplo del valore",
            "Mai sostituire al 80%+ possesso prima del 75'",
            "Mai inseguire palla individualmente",
        ],
        "bullets_en": [],
        "table_it": None,
        "table_en": None,
    },
    {
        "id": "kpi",
        "order": 12,
        "category_en": "KPI - am I playing my style?",
        "category_it": "KPI - sto giocando il mio stile?",
        "icon": "stats-chart-outline",
        "summary_it": "Target a regime (non a singola partita).",
        "summary_en": "",
        "bullets_it": [],
        "bullets_en": [],
        "table_it": [
            {"label": "Possesso medio", "value": ">= 65% (sotto = non controllo il tempo)"},
            {"label": "Passaggi completati", "value": ">= 88% (sotto = rischio troppo)"},
            {"label": "Tiri totali", "value": ">= 2x avversario (sotto = non finalizzo)"},
            {"label": "Goal subiti/partita", "value": "< 1.0 (sopra = buchi difensivi)"},
            {"label": "Goal fatti/partita", "value": ">= 1.5 (sotto = sistema sterile)"},
            {"label": "Passaggi per azione", "value": ">= 15 (sotto = troppo verticale)"},
        ],
        "table_en": None,
    },
    {
        "id": "checklist",
        "order": 13,
        "category_en": "Pre-match 60s checklist",
        "category_it": "Checklist pre-partita 60 secondi",
        "icon": "checkmark-done-outline",
        "summary_it": "60 secondi prima del calcio d'inizio.",
        "summary_en": "",
        "bullets_it": [
            "Morale 80/80 sui titolari?",
            "Condizione 80/80 sui titolari?",
            "Modulo salvato e caricato?",
            "Freccia BLU sul DMC verificata?",
            "AML/AMR sono dribbler veri (non lenti)?",
            "Avversario ha DMC? (decide 4-3-3 vs 3-1-5-1)",
            "Penalty Specialist e Free Kick Specialist in campo?",
        ],
        "bullets_en": [],
        "table_it": None,
        "table_en": None,
    },
]

# ==================== SET PIECE ====================
# Calci piazzati: rigoristi, punizioni, corner offensivi, difesa corner, throw-in.
# Dati verificati da NotebookLM (notebook 7b0eba98 - 17 fonti meta 2026).

SET_PIECE = [
    {
        "id": "penalty",
        "order": 1,
        "category_en": "Penalty taker",
        "category_it": "Rigorista",
        "icon": "football-outline",
        "summary_it": "Quasi-infallibile con Penalty Specialist + morale Superb.",
        "summary_en": "",
        "bullets_it": [
            "Ruolo migliore: ST o AMC",
            "Attributi chiave: Finalizzazione + Tiro",
            "Abilita: Penalty Specialist (precisione quasi totale)",
            "Tie-breaker se ho piu candidati: morale 'Superb' (bonus performance maggiore)",
            "In alternativa: attributi bianchi > 150-200%",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Ruolo", "value": "ST o AMC"},
            {"label": "Attributi", "value": "Finalizzazione + Tiro"},
            {"label": "Abilita chiave", "value": "Penalty Specialist"},
            {"label": "Tie-breaker", "value": "Morale Superb > attributi bianchi 150%+"},
        ],
        "table_en": None,
    },
    {
        "id": "free-kick",
        "order": 2,
        "category_en": "Direct free kicks",
        "category_it": "Punizioni dirette",
        "icon": "locate-outline",
        "summary_it": "Arma per sbloccare partite chiuse. Lo specialista cambia tutto.",
        "summary_en": "",
        "bullets_it": [
            "Ruoli ammessi: ST, AMC, MC",
            "Attributi: Tiro + Passaggio alti",
            "Abilita: Free Kick Specialist (essenziale)",
            "Da assegnare al miglior tiratore SEMPRE in formazione titolare",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Ruolo", "value": "ST / AMC / MC"},
            {"label": "Attributi", "value": "Tiro + Passaggio"},
            {"label": "Abilita chiave", "value": "Free Kick Specialist"},
            {"label": "Quando vale", "value": "Partite chiuse, sblocca da palla inattiva"},
        ],
        "table_en": None,
    },
    {
        "id": "corner-off",
        "order": 3,
        "category_en": "Offensive corners",
        "category_it": "Calci d'angolo offensivi",
        "icon": "flag-outline",
        "summary_it": "Massimizzo gioco aereo. Battitore con Cross alto + saltatori in area.",
        "summary_en": "",
        "bullets_it": [
            "Battitore: ML, MR, AML o AMR",
            "Attributo battitore: Cross (target 200%+)",
            "Abilita battitore: Corner Specialist",
            "In area: DC (forza fisica) + ST con playstyle Target Man",
            "Schema: massimizza saltatori forti vicino al portiere",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Battitore", "value": "ML / MR / AML / AMR"},
            {"label": "Attributo battitore", "value": "Cross 200%+"},
            {"label": "Abilita battitore", "value": "Corner Specialist"},
            {"label": "Saltatori in area", "value": "DC fisici + ST Target Man"},
            {"label": "Abilita saltatori", "value": "Aerial Threat"},
        ],
        "table_en": None,
    },
    {
        "id": "corner-def",
        "order": 4,
        "category_en": "Defending corners",
        "category_it": "Difesa sui corner",
        "icon": "shield-checkmark-outline",
        "summary_it": "Zona di default. Uomo solo se avversario ha saltatori dominanti.",
        "summary_en": "",
        "bullets_it": [
            "Marcatura standard: A Zona (stabilita)",
            "A Uomo: solo se l'avversario ha saltatori dominanti (forza errore)",
            "Abilita vitale: Aerial Defence su DMC Anchor Man o DC",
            "Abilita complementare: Defensive Wall (intercetta deviazioni sul dischetto)",
            "Mai lasciare la zona del dischetto scoperta",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Marcatura default", "value": "Zona"},
            {"label": "Marcatura alternativa", "value": "Uomo (se loro hanno saltatori top)"},
            {"label": "Abilita primaria", "value": "Aerial Defence (DMC/DC)"},
            {"label": "Abilita secondaria", "value": "Defensive Wall (dischetto)"},
        ],
        "table_en": None,
    },
    {
        "id": "throw-in",
        "order": 5,
        "category_en": "Long throw-in",
        "category_it": "Rimesse laterali lunghe",
        "icon": "hand-right-outline",
        "summary_it": "Skill Long Throw-in trasforma una rimessa in palla inattiva offensiva.",
        "summary_en": "",
        "bullets_it": [
            "Skill: Long Throw-in su DL o DR",
            "Effetto: rimessa diventa potenziale occasione da gol in area",
            "Allenare un solo terzino con questa skill e' sufficiente (il battitore titolare)",
            "Saltatori in area come per i corner (DC + ST Target Man)",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Skill", "value": "Long Throw-in"},
            {"label": "Su chi", "value": "DL o DR (basta uno titolare)"},
            {"label": "Effetto", "value": "Rimessa = occasione in area"},
        ],
        "table_en": None,
    },
]

# ==================== BATTLE CARDS ====================
# Schede di battaglia tra moduli: 4 verificate da NotebookLM (7b0eba98) + 6 derivate da MATCHUP_MATRIX.

BATTLE_CARDS = [
    {
        "id": "433-vs-4231-dmc",
        "order": 1,
        "category_en": "4-3-3 vs 4-2-3-1 with DMC",
        "category_it": "4-3-3 vs 4-2-3-1 con DMC",
        "icon": "shuffle-outline",
        "summary_it": "Si decide su fasce e cerchio centrocampo. Favorito: 4-2-3-1 con DMC. [Verificato NotebookLM]",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (4-3-3): Focus passaggi sulle Fasce per bypassare il DMC",
            "Mossa vincente A: Ali AML/AMR larghe con freccia rossa (Dual Position Advantage)",
            "Mossa vincente A: ST Falso 9 che scende e libera spazio per inserimenti",
            "Errore A: attaccare per vie centrali (DMC intercetta)",
            "Errore A: nessuna copertura sull'AMC avversario (assist letali tra le linee)",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Fasce + cerchio centrocampo"},
            {"label": "Verdetto", "value": "4-2-3-1 con DMC leggermente favorito"},
            {"label": "Perche favorito B", "value": "Il loro DMC schermo + 4 mediani vs 3 MC del 4-3-3"},
            {"label": "Giocatore chiave A", "value": "ST Falso 9"},
            {"label": "Fonte", "value": "NotebookLM 7b0eba98"},
        ],
        "table_en": None,
    },
    {
        "id": "433-vs-541-flat",
        "order": 2,
        "category_en": "4-3-3 vs 5-4-1 Flat (bus parking)",
        "category_it": "4-3-3 vs 5-4-1 Flat (bus parcheggiato)",
        "icon": "shuffle-outline",
        "summary_it": "Si decide su fasce e trequarti offensiva. Favorito: 4-3-3 con setup giusto. [Verificato NotebookLM]",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (4-3-3): Mentalita Offensiva da subito",
            "Mossa vincente A: Focus passaggi sulle Fasce (no centro)",
            "Mossa vincente A: ST Falso 9 attira fuori DC > varchi per inserimenti ali",
            "Errore A: attaccare al centro (e' il punto di forza del 5-4-1)",
            "Errore A: mentalita Normale o Difensiva (asseconda il loro piano 0-0)",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Fasce laterali + trequarti offensiva"},
            {"label": "Verdetto", "value": "4-3-3 favorito"},
            {"label": "Perche", "value": "5-4-1 ha probabilita di segnare vicine a zero"},
            {"label": "Giocatore chiave A", "value": "Ala AML/AMR con cross e dribbling"},
            {"label": "Fonte", "value": "NotebookLM 7b0eba98"},
        ],
        "table_en": None,
    },
    {
        "id": "451v-vs-433",
        "order": 3,
        "category_en": "4-5-1 V-Style vs 4-3-3",
        "category_it": "4-5-1 V-Style vs 4-3-3",
        "icon": "shuffle-outline",
        "summary_it": "Si decide su fasce e cerchio mediano. Favorito: 4-5-1 V-Style. [Verificato NotebookLM]",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (4-5-1 V): DMC con freccia BLU (stopper avanzato)",
            "Mossa vincente A: Focus sulle Fasce (4-3-3 manca copertura ML/MR)",
            "Mossa vincente A: Mentalita Difensiva/Normale + Force Counter-Attack ON",
            "Errore A: attaccare al centro (3 MC densi del 4-3-3)",
            "Errore A: non far ripiegare le ali > terzini isolati contro tridente",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Fasce + cerchio centrocampo"},
            {"label": "Verdetto", "value": "4-5-1 V-Style leggermente favorito"},
            {"label": "Perche", "value": "Tier S 2026, versatile, DMC equilibrio difensivo"},
            {"label": "Giocatore chiave A", "value": "DMC con freccia blu"},
            {"label": "Fonte", "value": "NotebookLM 7b0eba98"},
        ],
        "table_en": None,
    },
    {
        "id": "433-vs-433-mirror",
        "order": 4,
        "category_en": "4-3-3 vs 4-3-3 (mirror)",
        "category_it": "4-3-3 vs 4-3-3 (specchio)",
        "icon": "swap-horizontal-outline",
        "summary_it": "Si decide su duelli sulle fasce. Vince chi ha Team Balance migliore. [Verificato NotebookLM]",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente: ST Falso 9 (rompe la staticita dello specchio)",
            "Mossa vincente: Sovrapposizione terzini (DL/DR freccia ROSSA su veloci)",
            "Mossa vincente: gestire morale 'Superb' sui titolari chiave (bonus 2026)",
            "Errore: Pressing alto immediato (stamina esaurita ultimi 20')",
            "Errore: Insistere col focus 'Al Centro' (3 MC densi)",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Duelli individuali AML/AMR vs DL/DR"},
            {"label": "Verdetto", "value": "Vince chi ha Team Balance 9.2-10 + bianchi 150-200%"},
            {"label": "Cosa NON fare", "value": "Affidarsi a un 'mutante' con balance scarso"},
            {"label": "Giocatore chiave", "value": "Falso 9 + terzini veloci"},
            {"label": "Fonte", "value": "NotebookLM 7b0eba98"},
        ],
        "table_en": None,
    },
    {
        "id": "41212-nd-vs-433",
        "order": 5,
        "category_en": "4-1-2-1-2 ND vs 4-3-3",
        "category_it": "4-1-2-1-2 ND vs 4-3-3",
        "icon": "shuffle-outline",
        "summary_it": "Si decide al centro del campo. Favorito: 4-1-2-1-2 ND (controllo mediana).",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A: rosso su ST e AMC, passaggi rigorosamente Al Centro",
            "Mossa vincente A: pressing alto > sfrutta sovraccarico mediana 4v3",
            "Mossa vincente A: DMC + AMC creano linea verticale rapida",
            "Errore A: aprire il gioco sulle fasce (perde l'identita del modulo)",
            "Errore A: lasciare gli esterni del 4-3-3 liberi su contropiede",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Al centro - mediana 4v3"},
            {"label": "Verdetto", "value": "4-1-2-1-2 ND favorito (Tier S)"},
            {"label": "Perche", "value": "4 mediani vs 3 del 4-3-3 = dominio palla"},
            {"label": "Counter B (4-3-3)", "value": "Apri sulle fasce con AML/AMR larghi"},
            {"label": "Giocatore chiave A", "value": "AMC creativo"},
        ],
        "table_en": None,
    },
    {
        "id": "3151-vs-451v",
        "order": 6,
        "category_en": "3-1-5-1 vs 4-5-1 V-Style",
        "category_it": "3-1-5-1 vs 4-5-1 V-Style",
        "icon": "shuffle-outline",
        "summary_it": "Si decide sul controllo centrale. Scontro 'secret formation' vs 'versatile'.",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (3-1-5-1): sovraccarico mediana 5v3",
            "Mossa vincente A: DMC con freccia BLU + AMC con freccia ROSSA",
            "Mossa vincente A: pressing alto + mentalita Offensiva",
            "Errore A: difesa a 3 esposta se l'AMR/AML avversario riceve in profondita",
            "Errore A: se l'avversario contropiede > retroguardia a rischio",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Trequarti offensiva del 3-1-5-1"},
            {"label": "Verdetto", "value": "3-1-5-1 favorito se l'avversario non contropiede"},
            {"label": "Rischio A", "value": "Difesa a 3 + DMC unico = vulnerabile 1v1 ali"},
            {"label": "Giocatore chiave A", "value": "AMC con Shadow Striker"},
        ],
        "table_en": None,
    },
    {
        "id": "4231-dmc-vs-442",
        "order": 7,
        "category_en": "4-2-3-1 with DMC vs 4-4-2 Classic",
        "category_it": "4-2-3-1 con DMC vs 4-4-2 Classico",
        "icon": "shuffle-outline",
        "summary_it": "Si decide tra le linee. Favorito: 4-2-3-1 (AMC libero tra centrocampo e difesa).",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (4-2-3-1): AMC con Shadow Striker tra le linee del 4-4-2",
            "Mossa vincente A: passaggi corti + possesso (no DMC avversario)",
            "Mossa vincente A: freccia rossa sull'ala lato debole del 4-4-2",
            "Errore A: pressing alto > il 4-4-2 lancia lungo sulle due punte",
            "Errore A: non proteggere i terzini contro ML/MR avversari",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Spazio tra centrocampo e difesa del 4-4-2"},
            {"label": "Verdetto", "value": "4-2-3-1 favorito"},
            {"label": "Perche", "value": "AMC libero, 4-4-2 senza DMC non sa marcarlo"},
            {"label": "Giocatore chiave A", "value": "AMC playmaker + Shadow Striker"},
        ],
        "table_en": None,
    },
    {
        "id": "451v-vs-541-flat",
        "order": 8,
        "category_en": "4-5-1 V-Style vs 5-4-1 Flat",
        "category_it": "4-5-1 V-Style vs 5-4-1 Flat",
        "icon": "shuffle-outline",
        "summary_it": "Si decide su pazienza e palle inattive. Match spesso 0-0 o 1-0 di misura.",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (4-5-1 V): AML/AMR larghi con cross alto (Corner Specialist)",
            "Mossa vincente A: ST Target Man in area su corner e cross",
            "Mossa vincente A: pazienza > mentalita Normale, non forzare Offensiva subito",
            "Errore A: forzare attacco centrale (linea a 5 invalicabile)",
            "Errore A: cambiare modulo a 30 min > perdi struttura",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Palle inattive + cross dalle fasce"},
            {"label": "Verdetto", "value": "4-5-1 V favorito ma deve essere paziente"},
            {"label": "Setup", "value": "Mentalita Normale, Sulle Fasce, pressing medio"},
            {"label": "Giocatore chiave A", "value": "ST Target Man con Aerial Threat"},
        ],
        "table_en": None,
    },
    {
        "id": "343-vs-433",
        "order": 9,
        "category_en": "3-4-3 vs 4-3-3",
        "category_it": "3-4-3 vs 4-3-3",
        "icon": "shuffle-outline",
        "summary_it": "Scontro offensivo, partita aperta. Favorito: 3-4-3 se ha terzini fluidificanti.",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (3-4-3): ML/MR con freccia rossa salgono come Wing-Back",
            "Mossa vincente A: 3 attaccanti vs 2 DC del 4-3-3 = superiorita centrale",
            "Mossa vincente A: pressing alto > il 4-3-3 ha solo 3 MC per costruire",
            "Errore A: difesa a 3 esposta se ali avversarie tagliano dentro",
            "Errore A: contropiede subito sulle fasce > perdo gli esterni alti",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Profondita centrale + ali del 4-3-3 vs Wing-Back"},
            {"label": "Verdetto", "value": "3-4-3 favorito se terzini fluidi"},
            {"label": "Perche", "value": "3 attaccanti vs 2 DC + Wing-Back larghi"},
            {"label": "Giocatore chiave A", "value": "ML/MR con Dual Position"},
        ],
        "table_en": None,
    },
    {
        "id": "442-vs-433",
        "order": 10,
        "category_en": "4-4-2 Classic vs 4-3-3",
        "category_it": "4-4-2 Classico vs 4-3-3",
        "icon": "shuffle-outline",
        "summary_it": "Si decide su rapidita transizioni. Favorito: 4-3-3 (controllo + Falso 9).",
        "summary_en": "",
        "bullets_it": [
            "Mossa vincente A (4-4-2): pressing alto sull'uscita palla del 4-3-3",
            "Mossa vincente A: ML/MR taglio dentro su contropiede",
            "Mossa vincente A: 2 ST sui DC avversari (sovrapposizione 2v2)",
            "Errore A: lasciare l'AMC inesistente (4-4-2 non ne ha) = trequarti libera per Falso 9",
            "Errore A: insistere palla a terra > serve lancio lungo verso le 2 punte",
        ],
        "bullets_en": [],
        "table_it": [
            {"label": "Si decide", "value": "Transizioni rapide (4-4-2 deve contropiede)"},
            {"label": "Verdetto", "value": "4-3-3 favorito (controllo possesso + Falso 9)"},
            {"label": "Counter A", "value": "Pressing alto + 2 ST verticali"},
            {"label": "Giocatore chiave A", "value": "Coppia di ST veloci e fisici"},
        ],
        "table_en": None,
    },
]

# ==================== SCOUT TIPS DATA (EXPANDED) ====================

SCOUT_TIPS = [
    {
        "id": '1',
        "category": 'defense',
        "title_en": 'Center Back Selection',
        "title_it": 'Selezione Difensori Centrali',
        "content_en": 'Look for CBs with high Tackling, Heading, and Positioning. Speed is important to recover against fast strikers. Prioritize players with 4+ stars. Use 2 DC vs 1 ST, 3 DC vs 2 ST, and DL-DC-DR vs ST-AML-AMR.',
        "content_it": 'Cerca DC con alto Contrasto, Colpo di Testa e Posizionamento. La velocità è importante per recuperare contro attaccanti veloci. Dai priorità a giocatori con 4+ stelle. Usa 2 DC vs 1 ST, 3 DC vs 2 ST, e DL-DC-DR vs ST-AML-AMR.'
    },
    {
        "id": '2',
        "category": 'midfield',
        "title_en": 'Midfield Balance',
        "title_it": 'Equilibrio a Centrocampo',
        "content_en": 'Have a mix of defensive (DMC) and attacking (AMC) midfielders. ML/MR should have good Crossing and Pace. Central midfielders need Passing and Stamina. Box-to-box midfielders are gold!',
        "content_it": 'Avere un mix di centrocampisti difensivi (DMC) e offensivi (AMC). ML/MR devono avere buon Cross e Velocità. I centrocampisti centrali necessitano Passaggio e Resistenza. I centrocampisti box-to-box sono oro!'
    },
    {
        "id": '3',
        "category": 'attack',
        "title_en": 'Striker Types',
        "title_it": 'Tipi di Attaccante',
        "content_en": 'Target men need Heading and Strength. Speedsters need Pace and Finishing. Complete forwards are rare but valuable. Use 2 ST to break 4 defenders, 3 ST (or ST-AML-AMR) to break 3 defenders.',
        "content_it": 'I pivot necessitano Colpo di Testa e Forza. I velocisti necessitano Velocità e Finalizzazione. Gli attaccanti completi sono rari ma preziosi. Usa 2 ST vs 4 difensori, 3 ST (o ST-AML-AMR) vs 3 difensori.'
    },
    {
        "id": '4',
        "category": 'training',
        "title_en": 'Training Priority',
        "title_it": 'Priorità Allenamento',
        "content_en": 'Focus training on your starting 11 first. Use Quick Training early in seasons. Save intensive drills for important matches. Maintain 80/80 teamplay before big games. Train GK: One-on-One, Aerial, Reflexes. Train DC: Tackling, Heading, Positioning.',
        "content_it": "Concentra l'allenamento prima sui titolari. Usa Allenamento Rapido all'inizio delle stagioni. Conserva gli esercizi intensivi per partite importanti. Mantieni 80/80 di affiatamento prima di grandi partite. Allena GK: Uno contro Uno, Aereo, Riflessi. Allena DC: Contrasto, Colpo di Testa, Posizionamento."
    },
    {
        "id": '5',
        "category": 'budget',
        "title_en": 'Token Management',
        "title_it": 'Gestione Token',
        "content_en": "Don't spend more than 30 tokens for a single auction player. Spend at least 15 tokens for youth academy per season. Never buy assistant players for more than 50 tokens. Sign TV rights for daily token bonus.",
        "content_it": "Non spendere più di 30 token per un singolo giocatore all'asta. Spendi almeno 15 token per l'accademia giovanile per stagione. Mai comprare assistenti per più di 50 token. Firma i diritti TV per bonus token giornaliero."
    },
    {
        "id": '6',
        "category": 'tactics',
        "title_en": 'Team Mentality Explained',
        "title_it": 'Mentalità di Squadra Spiegata',
        "content_en": "Hard Defending: Deep position, counter-attacks. Defending: Slightly higher, counter from midfield. Normal: Balanced approach. Attacking: Higher line, fullbacks support. Hard Attacking: All-out attack from opponent's half.",
        "content_it": 'Ultra Difensivo: Posizione arretrata, contropiedi. Difensivo: Leggermente più alto, contropiede dal centrocampo. Normale: Approccio bilanciato. Offensivo: Linea più alta, terzini in attacco. Ultra Offensivo: Attacco totale dalla metà campo avversaria.'
    },
    {
        "id": '7',
        "category": 'tactics',
        "title_en": 'Focus Passing Guide',
        "title_it": 'Guida Focus Passaggio',
        "content_en": 'Mixed: Play everywhere on pitch. Down Both Flanks: Use wide players to create. Right/Left Flank: Focus one side. Through the Middle: Central penetration. Match your passing to your formation!',
        "content_it": 'Misto: Gioca ovunque sul campo. Sulle Fasce: Usa esterni per creare. Fascia Destra/Sinistra: Concentra su un lato. Al Centro: Penetrazione centrale. Adatta i passaggi alla tua formazione!'
    },
    {
        "id": '8',
        "category": 'tactics',
        "title_en": 'Counter-Attack & Pressing',
        "title_it": 'Contropiede & Pressing',
        "content_en": 'Turn ON counter-attacks if opponent has more possession. Turn OFF if you dominate. High press wins ball high but tires players. Low press saves stamina for 2 daily games. Use high press against weaker teams!',
        "content_it": "Attiva contropiede se l'avversario ha più possesso. Disattiva se domini. Pressing alto recupera palla in alto ma stanca. Pressing basso risparmia resistenza per 2 partite giornaliere. Usa pressing alto contro squadre più deboli!"
    },
    {
        "id": '9',
        "category": 'tactics',
        "title_en": 'Marking & Tackling',
        "title_it": 'Marcatura & Contrasti',
        "content_en": "Zonal marking: Players stay in formation positions. Man-to-man: Mark specific attackers (tires defenders faster). Easy tackle: Few fouls, less risky. Hard tackle: More fouls but wins more balls. Match opponent's playstyle!",
        "content_it": "Marcatura a zona: Giocatori restano nelle posizioni. Uomo su uomo: Marca attaccanti specifici (stanca i difensori). Contrasto facile: Pochi falli, meno rischioso. Contrasto duro: Più falli ma recupera più palle. Adatta allo stile dell'avversario!"
    },
    {
        "id": '10',
        "category": 'tactics',
        "title_en": 'Offside Trap',
        "title_it": 'Fuorigioco',
        "content_en": 'Turn ON offside trap if opponent plays long balls to strikers. Turn OFF if opponent plays short passes. Risky against fast strikers! Best used with high defensive line and coordinated back line.',
        "content_it": "Attiva fuorigioco se l'avversario gioca palle lunghe agli attaccanti. Disattiva se gioca passaggi corti. Rischioso contro attaccanti veloci! Meglio con linea difensiva alta e difesa coordinata."
    },
    {
        "id": '11',
        "category": 'defense',
        "title_en": 'Full-Back Selection',
        "title_it": 'Selezione Terzini',
        "content_en": 'DR/DL need pace and stamina for overlapping runs. Look for good crossing and tackling. Wing-backs (DML/DMR) need even more stamina. In 3-back systems, they are your only width!',
        "content_it": 'DR/DL necessitano velocità e resistenza per sovrapposizioni. Cerca buon cross e contrasto. I esterni (DML/DMR) necessitano ancora più resistenza. Nei sistemi a 3, sono la tua unica ampiezza!'
    },
    {
        "id": '12',
        "category": 'attack',
        "title_en": 'Winger Selection',
        "title_it": 'Selezione Ali',
        "content_en": 'ML/MR need Pace, Crossing, and Dribbling. AML/AMR should have Finishing too. Inverted wingers (right-footed on left) can cut inside and shoot. Classic wingers provide crosses for headers.',
        "content_it": 'ML/MR necessitano Velocità, Cross e Dribbling. AML/AMR dovrebbero avere anche Finalizzazione. Ali invertite (destro a sinistra) possono rientrare e tirare. Ali classiche forniscono cross per colpi di testa.'
    },
    {
        "id": '13',
        "category": 'training',
        "title_en": 'Position Training Drills',
        "title_it": 'Esercizi per Posizione',
        "content_en": 'GK: One-on-One, Aerial, Reflexes. DC: Tackling, Heading, Positioning. DR/DL: Tackling, Pace, Crossing. MC: Passing, Tackling, Stamina. AMC: Passing, Finishing, Creativity. ST: Finishing, Heading, Pace.',
        "content_it": 'GK: Uno contro Uno, Aereo, Riflessi. DC: Contrasto, Colpo di Testa, Posizionamento. DR/DL: Contrasto, Velocità, Cross. MC: Passaggio, Contrasto, Resistenza. AMC: Passaggio, Finalizzazione, Creatività. ST: Finalizzazione, Colpo di Testa, Velocità.'
    },
    {
        "id": '14',
        "category": 'budget',
        "title_en": 'Youth Academy Tips',
        "title_it": 'Consigli Accademia Giovanile',
        "content_en": 'Try to get at least three 6-star players from youth academy every season. These young players will help your team win trophies in future seasons. Youth players develop faster with regular playing time.',
        "content_it": "Cerca di ottenere almeno tre giocatori da 6 stelle dall'accademia ogni stagione. Questi giovani giocatori aiuteranno la squadra a vincere trofei nelle stagioni future. I giovani si sviluppano più velocemente con minuti regolari."
    },
    {
        "id": '15',
        "category": 'general',
        "title_en": 'Beat Stronger Opponents',
        "title_it": 'Battere Avversari più Forti',
        "content_en": "Play counter-attacking football. Be strong in numbers in defense. Mark all opponent's attackers. Play long balls for counter-attacks - don't try to out-pass stronger midfielders. Let them attack, then strike!",
        "content_it": 'Gioca calcio di contropiede. Sii forte numericamente in difesa. Marca tutti gli attaccanti avversari. Gioca palle lunghe per contropiedi - non provare a superare centrocampisti più forti. Lasciali attaccare, poi colpisci!'
    },
    {
        "id": '16',
        "category": 'general',
        "title_en": 'Pre-Match Preparation',
        "title_it": 'Preparazione Pre-Partita',
        "content_en": "Always provide full Morale Boost and Fitness Condition before important matches. Add friends in Top Eleven - they help you get more possession during matches! Review opponent's formation and adjust tactics.",
        "content_it": 'Fornisci sempre Morale e Condizione al massimo prima di partite importanti. Aggiungi amici in Top Eleven - ti aiutano ad avere più possesso! Rivedi la formazione avversaria e adatta le tattiche.'
    },
    {
        "id": '17',
        "category": 'counter',
        "title_en": 'How to Beat 4-4-2 Classic',
        "title_it": 'Come Battere il 4-4-2 Classico',
        "content_en": 'Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Attack the flanks to exploit the absence of wide midfielders.',
        "content_it": "Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Attacca le fasce per sfruttare l'assenza di centrocampisti laterali."
    },
    {
        "id": '18',
        "category": 'counter',
        "title_en": 'How to Beat 4-3-3',
        "title_it": 'Come Battere il 4-3-3',
        "content_en": 'Best counter: 4-4-2. Setup — Mentality: Defensive, Focus Passing: Mixed, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: Yes. Tip: Use the four-man midfield to dominate central space.',
        "content_it": 'Miglior contromodulo: 4-4-2. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Misto, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: Sì. Consiglio: Usa il centrocampo a quattro per dominare lo spazio centrale.'
    },
    {
        "id": '19',
        "category": 'counter',
        "title_en": 'How to Beat 4-2-3-1',
        "title_it": 'Come Battere il 4-2-3-1',
        "content_en": 'Best counter: 4-1-3N-2. Setup — Mentality: Defensive, Focus Passing: Through the Middle, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: Yes. Tip: A DMC is vital for more clean sheets against this formation.',
        "content_it": 'Miglior contromodulo: 4-1-3N-2. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Al Centro, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: Sì. Consiglio: Un DMC è vitale per ottenere più clean sheet contro questo modulo.'
    },
    {
        "id": '20',
        "category": 'counter',
        "title_en": 'How to Beat 4-5-1 V-Style',
        "title_it": 'Come Battere il 4-5-1 V-Style',
        "content_en": 'Best counter: 4-3N-3. Setup — Mentality: Defensive, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Protect your flanks and attack theirs.',
        "content_it": "Miglior contromodulo: 4-3N-3. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Proteggi i tuoi fianchi e attacca quelli dell'avversario."
    },
    {
        "id": '21',
        "category": 'counter',
        "title_en": 'How to Beat 4-5-1 Flat',
        "title_it": 'Come Battere il 4-5-1 Flat',
        "content_en": 'Best counter: 4-1-4-1. Setup — Mentality: Normal, Focus Passing: Mixed, Passing: Short, Pressing: Medium, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Keep possession to neutralize their crowded midfield.',
        "content_it": 'Miglior contromodulo: 4-1-4-1. Impostazioni — Mentalità: Normale, Focus Passaggi: Misto, Passaggi: Corto, Pressing: Medio, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Mantieni il possesso palla per neutralizzare il loro centrocampo folto.'
    },
    {
        "id": '22',
        "category": 'counter',
        "title_en": 'How to Beat 3-5-2 Flat',
        "title_it": 'Come Battere il 3-5-2 Flat',
        "content_en": 'Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Exploit the wide weakness of the three-man defense with fast wingers.',
        "content_it": 'Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Sfrutta la debolezza laterale della difesa a tre con ali veloci.'
    },
    {
        "id": '23',
        "category": 'counter',
        "title_en": 'How to Beat 5-4-1 Flat',
        "title_it": 'Come Battere il 5-4-1 Flat',
        "content_en": 'Best counter: 4-4-2. Setup — Mentality: Attacking, Focus Passing: Mixed, Passing: Short, Pressing: High, Tackling: Normal, Marking: Man-to-Man, Offside Trap: No. Tip: Raise your line and pressing to break down the defensive wall.',
        "content_it": 'Miglior contromodulo: 4-4-2. Impostazioni — Mentalità: Offensivo, Focus Passaggi: Misto, Passaggi: Corto, Pressing: Alto, Contrasti: Normale, Marcatura: A Uomo, Trappola Fuorigioco: No. Consiglio: Alza il baricentro e il pressing per scardinare il muro difensivo.'
    },
    {
        "id": '24',
        "category": 'counter',
        "title_en": 'How to Beat 4-1-2-1-2 Narrow Diamond',
        "title_it": 'Come Battere il 4-1-2-1-2 Narrow Diamond',
        "content_en": 'Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Stretch play to bypass the density of the central diamond.',
        "content_it": 'Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Allarga il gioco per aggirare la densità del rombo centrale.'
    },
    {
        "id": '25',
        "category": 'counter',
        "title_en": 'How to Beat 4-2-2-2 Hexagon',
        "title_it": 'Come Battere il 4-2-2-2 Hexagon',
        "content_en": 'Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Wingers are essential to hit this versatile formation.',
        "content_it": 'Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Le ali sono fondamentali per colpire questo modulo versatile.'
    },
    {
        "id": '26',
        "category": 'counter',
        "title_en": 'How to Beat 3-4-1-2',
        "title_it": 'Come Battere il 3-4-1-2',
        "content_en": 'Best counter: 4-1-2-1-2 ND. Setup — Mentality: Normal, Focus Passing: Through the Middle, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Man-to-Man, Offside Trap: No. Tip: Attack the sides of the CBs if the opponent has no wide players.',
        "content_it": "Miglior contromodulo: 4-1-2-1-2 ND. Impostazioni — Mentalità: Normale, Focus Passaggi: Al Centro, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Uomo, Trappola Fuorigioco: No. Consiglio: Attacca i lati dei DC se l'avversario non ha ali laterali."
    },
    {
        "id": '27',
        "category": 'counter',
        "title_en": 'How to Beat 3-4-3',
        "title_it": 'Come Battere il 3-4-3',
        "content_en": 'Best counter: 4-2-2-2 Hexagon. Setup — Mentality: Defensive, Focus Passing: Down Both Flanks, Passing: Mixed, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Exploit the open space on the flanks of the three-man defense.',
        "content_it": 'Miglior contromodulo: 4-2-2-2 Hexagon. Impostazioni — Mentalità: Difensivo, Focus Passaggi: Su Entrambe le Fasce, Passaggi: Misto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Sfrutta lo spazio aperto sulle fasce della difesa a tre.'
    },
    {
        "id": '28',
        "category": 'counter',
        "title_en": 'How to Beat 4-1-3-2 Wide',
        "title_it": 'Come Battere il 4-1-3-2 Wide',
        "content_en": "Best counter: 4-5-1 V-Style. Setup — Mentality: Normal, Focus Passing: Mixed, Passing: Short, Pressing: Low, Tackling: Normal, Marking: Zonal, Offside Trap: No. Tip: Keep balance between the lines so you're not caught out.",
        "content_it": "Miglior contromodulo: 4-5-1 V-Style. Impostazioni — Mentalità: Normale, Focus Passaggi: Misto, Passaggi: Corto, Pressing: Basso, Contrasti: Normale, Marcatura: A Zona, Trappola Fuorigioco: No. Consiglio: Mantieni l'equilibrio tra le linee per non farti sorprendere."
    },
    {
        "id": '29',
        "category": 'counter',
        "title_en": 'How to Beat 5-2-1-2 X-Style',
        "title_it": 'Come Battere il 5-2-1-2 X-Style',
        "content_en": 'Best counter: 4-1-2-1-2 ND. Setup — Mentality: Normal, Focus Passing: Mixed, Passing: Mixed, Pressing: High, Tackling: Normal, Marking: Man-to-Man, Offside Trap: No. Tip: Intensify pressing to win the ball back quickly.',
        "content_it": 'Miglior contromodulo: 4-1-2-1-2 ND. Impostazioni — Mentalità: Normale, Focus Passaggi: Misto, Passaggi: Misto, Pressing: Alto, Contrasti: Normale, Marcatura: A Uomo, Trappola Fuorigioco: No. Consiglio: Intensifica il pressing per recuperare palla velocemente.'
    },
    {
        "id": '30',
        "category": 'scenario',
        "title_en": 'Defending a Lead',
        "title_it": 'In Vantaggio',
        "content_en": "When you hold a comfortable lead, switch to a defensive or 'park-the-bus' mentality using formations like the 5-4-1. Lower the pressing and set zonal marking to protect the result and conserve energy.",
        "content_it": "Se hai un vantaggio rassicurante, passa a una mentalità difensiva o 'Park-the-Bus' usando moduli come il 5-4-1. Riduci il pressing a basso e imposta la marcatura zonale per proteggere il risultato e conservare energia."
    },
    {
        "id": '31',
        "category": 'scenario',
        "title_en": 'Chasing the Game',
        "title_it": 'In Svantaggio',
        "content_en": 'Around the 60th minute, switch to aggressive formations like the 4-2-4 or 3-4-1-2 to add attacking weight. Turn on high pressing and man-to-man marking to force errors and win the ball back quickly.',
        "content_it": "Intorno al 60° minuto, passa a formazioni aggressive come il 4-2-4 o il 3-4-1-2 per aumentare il peso offensivo. Attiva il pressing alto e la marcatura a uomo per forzare l'avversario all'errore e recuperare palla velocemente."
    },
    {
        "id": '32',
        "category": 'scenario',
        "title_en": 'Managing the 90 Minutes',
        "title_it": 'Gestione dei Tempi',
        "content_en": "Start the match with low pressing to preserve your key players' fitness. In the second half, raise the intensity and bring on a striker or winger from the bench if you need decisive late goals.",
        "content_it": "Inizia il match con pressing basso per conservare la condizione fisica dei tuoi giocatori chiave. Nel secondo tempo, aumenta l'intensità e inserisci un attaccante o un'ala dalla panchina se hai bisogno di segnare gol decisivi nel finale."
    },
    {
        "id": '33',
        "category": 'scenario',
        "title_en": 'Quick Tactical Switches',
        "title_it": 'Cambi Tattici Rapidi',
        "content_en": "Save up to four different formations in the Team menu for instant tactical switches during the live match. This lets you react to the opponent's moves without wasting precious time or unnecessary substitutions.",
        "content_it": "Salva fino a quattro formazioni diverse nel menu Squadra per effettuare cambi tattici istantanei durante il match live. Questa strategia ti permette di reagire alle mosse dell'avversario senza sprecare tempo prezioso o sostituzioni inutili."
    },
    {
        "id": '34',
        "category": 'morale',
        "title_en": 'Morale Baseline',
        "title_it": 'Baseline del Morale',
        "content_en": "The 'Good' morale level is now the new baseline and is more impactful than the old 'Superb'. Always check the Morale tab to see if players need more game time or if events like a hat-trick have boosted their state.",
        "content_it": "Il livello di morale 'Buono' è ora il nuovo standard di base ed è più impattante del vecchio 'Superbo'. Controlla sempre il tab Morale per capire se i giocatori necessitano di più minutaggio o se eventi come una tripletta hanno aumentato il loro stato."
    },
    {
        "id": '35',
        "category": 'morale',
        "title_en": 'Condition & Pressing',
        "title_it": 'Condizione e Pressing',
        "content_en": "Avoid turning on high pressing too early so you don't drain fitness before the last 10 minutes. Condition that drops too low drastically reduces player effectiveness in the crucial phases of the match.",
        "content_it": "Evita di attivare il pressing alto troppo presto nel match per non esaurire la condizione fisica prima degli ultimi 10 minuti. Una condizione troppo bassa riduce drasticamente l'efficacia dei giocatori nelle fasi cruciali della partita."
    },
    {
        "id": '36',
        "category": 'morale',
        "title_en": 'Team Balance',
        "title_it": 'Equilibrio di Squadra',
        "content_en": "Keep your Team Balance score between 9.2 and 10 to ensure the team performs at its peak. Having a single overpowered ('mutant') player can paradoxically lower overall quality and lead to losses against weaker teams.",
        "content_it": "Mantieni il punteggio di 'Team Balance' tra 9.2 e 10 per garantire che la squadra performi al massimo delle sue potenzialità. Avere un singolo giocatore 'overpowered' (mutante) può paradossalmente abbassare la qualità complessiva e portare a sconfitte contro team più deboli."
    },
    {
        "id": '37',
        "category": 'market',
        "title_en": 'Hunting Fast Trainers',
        "title_it": 'Ricerca Fast Trainers',
        "content_en": "At auctions, focus on buying 'fast trainers' who grow quickly with training. Following specific lists of these talents lets you build a competitive squad while saving tokens and resources.",
        "content_it": "Durante le aste, concentrati sull'acquisto di giocatori definiti 'fast trainers' che crescono rapidamente con l'allenamento. Seguire liste specifiche di questi talenti ti permette di costruire una squadra competitiva risparmiando token e risorse."
    },
    {
        "id": '38',
        "category": 'market',
        "title_en": 'Stockpiling Tokens',
        "title_it": 'Accumulo di Token',
        "content_en": 'Use the daily Special Sponsor and free events like the Draw Frenzy to stockpile tokens without spending real money. A good token reserve is essential to reinforce key roles during the hot phases of the season.',
        "content_it": "Sfrutta quotidianamente lo Special Sponsor e gli eventi gratuiti come il 'Draw Frenzy' per accumulare token senza spendere denaro reale. Una buona riserva di token è fondamentale per rinforzare i ruoli chiave durante le fasi calde della stagione."
    },
    {
        "id": '39',
        "category": 'market',
        "title_en": 'Auction Strategy',
        "title_it": 'Strategia nelle Aste',
        "content_en": "Carefully analyze a player's 'white' attributes before bidding, favoring those with very high key stats and low 'grey' stats. Don't rebid compulsively — judge whether the token cost is justified by the player's growth potential.",
        "content_it": "Analizza attentamente le abilità 'bianche' di un giocatore prima di offrire, preferendo chi ha statistiche chiave altissime e statistiche 'grigie' basse. Non rilanciare compulsivamente, ma valuta se il costo in token è giustificato dal potenziale di crescita del giocatore."
    },
    {
        "id": '40',
        "category": 'skills',
        "title_en": 'The False Nine Dominance',
        "title_it": 'Il Dominio del Falso Nove',
        "content_en": "In the 2026 meta the False Nine is considered the strongest striker playstyle. It lets the forward drop deep, dragging out the centre-backs and creating lethal gaps for the wingers' runs.",
        "content_it": 'Nel meta 2026, il False Nine è considerato lo stile di gioco più forte per un attaccante. Questo ruolo permette alla punta di arretrare, attirando fuori i difensori centrali e creando varchi letali per gli inserimenti delle ali.'
    },
    {
        "id": '41',
        "category": 'skills',
        "title_en": 'Wingers & Dual Position',
        "title_it": 'Ali e Doppio Ruolo',
        "content_en": 'Use players with the Dual Position ability (AML/AMR) to exploit weaknesses in opposing defenses. Wingers are essential to overload the flanks against formations that defend poorly out wide, like the 4-5-1 V-Style.',
        "content_it": "Utilizza giocatori con abilità 'Dual Position' (AML/AMR) per sfruttare i punti deboli delle difese avversarie. Le ali sono essenziali per sovraccaricare le fasce contro moduli che difendono male lateralmente, come il 4-5-1 V-Style."
    },
    {
        "id": '42',
        "category": 'skills',
        "title_en": 'Arrows & Pace',
        "title_it": 'Frecce e Velocità',
        "content_en": "Apply the red (forward) arrow to fast players to push them forward, and the blue (back) arrow to slower ones to keep them in defensive position. This trick optimizes the team's dynamic positioning based on each player's physical traits.",
        "content_it": 'Applica la freccia rossa ai giocatori con alta velocità per spingerli in fase offensiva e la freccia blu a quelli più lenti per mantenerli in posizione difensiva. Questo trucco ottimizza il posizionamento dinamico della squadra in base alle caratteristiche fisiche dei singoli.'
    },
    {
        "id": '43',
        "category": 'skills',
        "title_en": 'Shadow Striker Role',
        "title_it": 'Ruolo Shadow Striker',
        "content_en": "Set up an AMC with the Shadow Striker ability to create a 'hidden' threat that breaks into the empty spaces left by the defense. This is especially effective when the opponent has no DMC protecting the area in front of the back line.",
        "content_it": "Imposta un AMC con l'abilità Shadow Striker per creare una minaccia 'segreta' che si inserisce negli spazi vuoti lasciati dalla difesa. Questa posizione è particolarmente efficace se l'avversario non utilizza un DMC per proteggere l'area davanti ai difensori."
    },
    {
        "id": '44',
        "category": 'skills',
        "title_en": 'DMC for Clean Sheets',
        "title_it": 'DMC per i Clean Sheet',
        "content_en": "Adding a DMC is vital in almost any formation to increase your chance of a clean sheet. Acting as an 'advanced stopper', he screens the defense and intercepts the play of the opponent's most dangerous AMCs.",
        "content_it": "L'inserimento di un DMC è vitale in quasi ogni formazione per aumentare la probabilità di non subire gol. Agendo come uno 'stopper avanzato', scherma la difesa e intercetta le trame di gioco degli AMC avversari più pericolosi."
    },
    {
        "id": '45',
        "category": 'arrows',
        "title_en": 'Red Arrow (Attack)',
        "title_it": 'Freccia Rossa (Attacco)',
        "content_en": "The red arrow signals an attacking mentality and pushes the player forward to join the attack. It's useful for wingers or strikers who need to exploit empty spaces and create shooting chances.",
        "content_it": "La freccia rossa indica una mentalità offensiva e spinge il giocatore ad avanzare per partecipare alla manovra d'attacco. È utile per le ali o gli attaccanti che devono sfruttare gli spazi vuoti e creare opportunità di tiro."
    },
    {
        "id": '46',
        "category": 'arrows',
        "title_en": 'Blue Arrow (Defense)',
        "title_it": 'Freccia Blu (Difesa)',
        "content_en": "The blue arrow gives defensive instructions, forcing the player to hold a deeper position. It's used to ensure unit solidity and stop defenders pushing up too far and leaving gaps.",
        "content_it": 'La freccia blu assegna istruzioni difensive, costringendo il giocatore a mantenere una posizione più arretrata. Garantisce la solidità del reparto e impedisce ai difensori di salire troppo lasciando varchi agli avversari.'
    },
    {
        "id": '47',
        "category": 'arrows',
        "title_en": 'Setting Arrows',
        "title_it": 'Selezione delle Frecce',
        "content_en": 'To set arrows, tap the player in the Team menu: one tap sets the red arrow, a second the blue arrow, a third removes it. This turns a standard formation into an asymmetric or more versatile shape.',
        "content_it": 'Per applicare le frecce clicca sul giocatore nel menu Squadra: un clic attiva la freccia rossa, un secondo la freccia blu e un terzo la rimuove. Così trasformi una formazione standard in un modulo asimmetrico o più versatile.'
    },
    {
        "id": '48',
        "category": 'arrows',
        "title_en": 'Impact on Condition',
        "title_it": 'Impatto sulla Condizione',
        "content_en": "Activating too many attacking arrows, especially with high pressing, drastically drains fitness over time. Better to start with few arrows and activate them in the second half so you don't burn stamina before the finish.",
        "content_it": 'Attivare troppe frecce offensive, specialmente con pressing alto, riduce drasticamente la condizione fisica nel tempo. Meglio iniziare con poche frecce e attivarle nel secondo tempo per non esaurire la stamina prima del finale.'
    },
    {
        "id": '49',
        "category": 'arrows',
        "title_en": 'Arrows and Pace',
        "title_it": 'Frecce e Velocità',
        "content_en": "Key rule: red arrow for fast players, blue arrow for slower ones. This lets pacey players burst into space while slow ones hold position so they aren't beaten on the counter.",
        "content_it": 'Regola fondamentale: freccia rossa ai giocatori veloci, freccia blu ai più lenti. Così i velocisti scattano negli spazi mentre i lenti restano in posizione per non farsi superare in contropiede.'
    },
    {
        "id": '50',
        "category": 'arrows',
        "title_en": 'Mistakes to Avoid',
        "title_it": 'Errori da Evitare',
        "content_en": "Avoid red arrows on both full-backs if your CBs don't outnumber the strikers — a long ball could break your defense. And don't use aggressive arrows too early against strong opponents to avoid physical collapse.",
        "content_it": 'Evita la freccia rossa a entrambi i terzini se i DC non hanno superiorità numerica sulle punte: un lancio lungo distruggerebbe la difesa. E non usare frecce aggressive troppo presto contro avversari forti, per evitare crolli fisici.'
    },
    {
        "id": '51',
        "category": 'meta',
        "title_en": 'False 9: Why It Dominates',
        "title_it": 'Falso Nove: Perché Domina',
        "content_en": "The False Nine is the strongest striker playstyle in the 2026 meta, able to break down even stronger opponents' defenses. It dominates because the forward gives the centre-backs no reference point, creating lethal gaps for teammates' runs.",
        "content_it": "Il Falso Nove è lo stile di gioco per l'attaccante più potente nel meta 2026, capace di scardinare anche difese di avversari più forti. Domina perché la punta non dà punti di riferimento ai DC, creando spazi letali per gli inserimenti dei compagni."
    },
    {
        "id": '52',
        "category": 'meta',
        "title_en": 'False 9: Key Attributes',
        "title_it": 'Falso Nove: Attributi Chiave',
        "content_en": "You need very high 'white skills', especially finishing, shooting, passing and creativity. A 6-star forward with optimized white attributes beats one with more stars but too many grey stats.",
        "content_it": "Servono 'white skills' altissime, in particolare finalizzazione, tiro, passaggio e creatività. Un attaccante da 6 stelle con attributi bianchi ottimizzati è preferibile a uno con più stelle ma troppe statistiche grigie."
    },
    {
        "id": '53',
        "category": 'meta',
        "title_en": 'False 9: Best Formations',
        "title_it": 'Falso Nove: Moduli Migliori',
        "content_en": 'The most effective systems for the False Nine are the 4-3-3 and 4-5-1 V-Style, forming a dynamic front three and exploiting the forward dropping deep to link play with midfield.',
        "content_it": 'I sistemi più efficaci per il Falso Nove sono il 4-3-3 e il 4-5-1 V-Style, che formano un tridente dinamico e sfruttano la capacità della punta di abbassarsi per collegare il gioco col centrocampo.'
    },
    {
        "id": '54',
        "category": 'meta',
        "title_en": 'False 9: Arrows & Support',
        "title_it": 'Falso Nove: Frecce e Supporto',
        "content_en": 'Pair the False Nine with two wingers (AML/AMR) on red arrows that use the Dual Position to cut into the box. The forward stays with no arrow or a blue arrow to drag the CBs out, freeing the wingers in the space.',
        "content_it": 'Affianca al Falso Nove due ali (AML/AMR) con freccia rossa che sfruttino il Dual Position per tagliare in area. La punta resta senza freccia o con freccia blu per attirare i DC, lasciando le ali libere negli spazi.'
    },
    {
        "id": '55',
        "category": 'meta',
        "title_en": 'Defending vs the False 9',
        "title_it": 'Come Difendersi dal Falso Nove',
        "content_en": 'Against a False Nine the best counter is the 4-1-3-1-1, with the DMC and an MC sitting deep to choke the space between defense and midfield. Use a defensive mentality, zonal marking and pressing in your own half.',
        "content_it": 'Contro un Falso Nove la contromossa migliore è il 4-1-3-1-1, con DMC e un MC molto arretrati per soffocare lo spazio tra difesa e mediana. Usa mentalità difensiva, marcatura a zona e pressing nella tua metà campo.'
    },
    {
        "id": '56',
        "category": 'meta',
        "title_en": 'False 9: Mistakes to Avoid',
        "title_it": 'Falso Nove: Errori da Evitare',
        "content_en": "Don't build the whole team around a single super-striker while ignoring Team Balance (keep it between 9.2 and 10). And don't turn on high pressing too early: it drains the fitness you need in the closing minutes.",
        "content_it": 'Non concentrare tutta la squadra su un solo super attaccante ignorando il Team Balance (tienilo tra 9.2 e 10). E non attivare il pressing alto troppo presto: riduce la condizione fisica nei minuti finali.'
    },
    {
        "id": '57',
        "category": 'economy',
        "title_en": 'Special Sponsor First',
        "title_it": 'Special Sponsor Prima di Tutto',
        "content_en": 'Always sign the Special Sponsor (the daily tokens one) before any other deal. Over a season the cumulative income is the highest free token source in the game.',
        "content_it": "Firma sempre lo Special Sponsor (quello dei token giornalieri) prima di ogni altro accordo. Sull'arco di una stagione l'introito cumulato è la fonte di token gratuita più alta del gioco."
    },
    {
        "id": '58',
        "category": 'economy',
        "title_en": 'Daily Free Events',
        "title_it": 'Eventi Gratuiti Quotidiani',
        "content_en": "Open the game every day for Draw Frenzy, free packs and rewards. Five minutes of activity equal 2-5 free tokens — over a season that's a serious budget.",
        "content_it": "Apri il gioco ogni giorno per Draw Frenzy, pacchetti gratuiti e ricompense. Cinque minuti di attività valgono 2-5 token gratis — sull'arco della stagione è un budget serio."
    },
    {
        "id": '59',
        "category": 'economy',
        "title_en": 'Auction Ceiling',
        "title_it": 'Tetto in Asta',
        "content_en": "Set yourself a max-token limit per auction (e.g. 30 tokens for a key role, 15 for a backup). Never go beyond, even in the heat of bidding: tomorrow there's a better one.",
        "content_it": "Datti un limite massimo di token per ogni asta (es. 30 token per un ruolo chiave, 15 per una riserva). Non superarlo mai, anche nella foga: domani ce n'è uno migliore."
    },
    {
        "id": '60',
        "category": 'economy',
        "title_en": 'Youth Academy ROI',
        "title_it": 'ROI Accademia Giovanile',
        "content_en": '15 tokens spent on the youth academy each season give an average of 1-2 six-star young players. Three years like this and you have a top squad without buying anyone.',
        "content_it": "15 token spesi nell'accademia giovanile ogni stagione regalano in media 1-2 giovani da 6 stelle. Tre stagioni così e hai una rosa top senza comprare nessuno."
    },
    {
        "id": '61',
        "category": 'economy',
        "title_en": 'Sell Before Negative',
        "title_it": 'Vendere Prima del Negativo',
        "content_en": "A 27-year-old player still sells well; a 30-year-old loses most of his value. Plan generational changes 2 seasons in advance, you won't take losses.",
        "content_it": 'Un giocatore di 27 anni si vende ancora bene; uno di 30 perde la maggior parte del valore. Pianifica i ricambi generazionali con 2 stagioni di anticipo, non andrai in perdita.'
    },
    {
        "id": '62',
        "category": 'economy',
        "title_en": 'Friend Bonus Multiplier',
        "title_it": 'Moltiplicatore Bonus Amici',
        "content_en": "Add 30+ active friends from the official Top Eleven communities. Their daily bonuses give you free tokens, packs and gifts: it's the equivalent of an extra sponsor.",
        "content_it": 'Aggiungi 30+ amici attivi dalle community ufficiali Top Eleven. I loro bonus quotidiani ti regalano token, pacchetti e gift gratis: equivale a uno sponsor extra.'
    },
    {
        "id": '63',
        "category": 'economy',
        "title_en": "Don't Pay to Skip",
        "title_it": 'Non Pagare per Saltare',
        "content_en": "Tokens to instantly heal an injury or speed up the academy are the worst purchases in the game. Wait the 24h: you'll save tokens to use where it really matters.",
        "content_it": "I token per curare istantaneamente un infortunio o accelerare l'accademia sono i peggiori acquisti del gioco. Aspetta le 24h: risparmierai token per spenderli dove conta davvero."
    },
    {
        "id": '64',
        "category": 'economy',
        "title_en": 'Right Stadium Size',
        "title_it": 'Stadio della Misura Giusta',
        "content_en": "Don't over-grow your stadium. A fully-filled 35,000-seat stadium gives more income (and fan boost) than a half-empty 60,000-seat one.",
        "content_it": 'Non sovradimensionare lo stadio. Uno stadio da 35.000 posti sempre pieno rende più (anche in bonus tifo) di uno da 60.000 sempre mezzo vuoto.'
    },
    {
        "id": '65',
        "category": 'general',
        "title_en": 'Team Building: build the spine first',
        "title_it": 'Team Building: prima costruisci la spina dorsale',
        "content_en": "Don't buy 11 stars together: focus your investments first on the central spine (GK · CB · DMC · AMC · ST). With those 5 roles at 6 stars and the rest at 5, you win 80% of matches. Quality at the center beats quality spread thin.",
        "content_it": "Non comprare 11 stelle insieme: concentra gli investimenti prima sulla colonna centrale (GK · DC · DMC · AMC · ST). Con quei 5 ruoli a 6 stelle e il resto a 5, vinci l'80% delle partite. La qualità al centro batte la qualità sparsa."
    },
    {
        "id": '66',
        "category": 'tactics',
        "title_en": '4-2-3-1 Defensive: a hidden weapon',
        "title_it": '4-2-3-1 Difensivo: arma nascosta',
        "content_en": 'Most players use the 4-2-3-1 attacking. Try it with Defensive mentality, blue arrows on the back four and the two MCs, red arrows only on AML/AMR. You concede little, the AMC orchestrates the counter. Lethal against attacking opponents who push high.',
        "content_it": "La maggior parte dei giocatori usa il 4-2-3-1 in attacco. Provalo con mentalità Difensiva, frecce blu sulla difesa a quattro e sui due MC, frecce rosse solo su AML/AMR. Concedi poco, l'AMC orchestra il contropiede. Letale contro avversari offensivi che salgono."
    },
    {
        "id": '67',
        "category": 'tactics',
        "title_en": 'Retro formations coming back',
        "title_it": 'Moduli retrò che tornano',
        "content_en": "In high-level associations the 2-3-2-3 (modern WM) and the 3-3-3-1 are coming back: surprise the opponent who doesn't know how to counter them. Use them only if you have very mobile players with the Dual Position ability.",
        "content_it": "Nei livelli alti delle associazioni stanno tornando moduli come il 2-3-2-3 (W-M moderno) e il 3-3-3-1: sorprendono l'avversario che non sa come contrastarli. Usali solo se hai giocatori molto mobili con abilità Dual Position."
    },
    {
        "id": '68',
        "category": 'tactics',
        "title_en": 'Tiki-Taka requires the DMC playmaker',
        "title_it": 'Il Tiki-Taka richiede il DMC playmaker',
        "content_en": "The mistake of those who try the Tiki-Taka in Top Eleven: putting the playmaker at AMC. Wrong: in Barça-2011 it was Busquets at DMC who started every action. Place a Deep-Lying Playmaker at DMC with maxed Passing/Creativity: it's the difference between 'it works' and 'it doesn't work'.",
        "content_it": "L'errore di chi prova il Tiki-Taka in Top Eleven: mettere il regista come AMC. Sbagliato: nel Barça-2011 era Busquets, DMC, a innescare ogni azione. Metti un Regista Arretrato come DMC con Passaggio/Creatività al massimo: è la differenza tra 'funziona' e 'non funziona'."
    },
    {
        "id": '69',
        "category": 'meta',
        "title_en": 'FM-style 4-2-3-1 attacking',
        "title_it": '4-2-3-1 attaccante stile FM',
        "content_en": 'VictorHugo-style 4-2-3-1 (popular among Football Manager fans): Attacking mentality, Through the Middle, AMC with Shadow Striker ability, AML/AMR inverted (red arrows). Drowns the opponent with central pressure and creative passes; brutal against weaker teams.',
        "content_it": "Il 4-2-3-1 stile VictorHugo (popolare tra i fan di Football Manager): mentalità Offensiva, passaggi Al Centro, AMC con abilità Shadow Striker, AML/AMR invertiti (frecce rosse). Affoga l'avversario con pressione centrale e passaggi creativi; brutale contro avversari più deboli."
    },
    {
        "id": '70',
        "category": 'meta',
        "title_en": "Vertical Tiki-Taka: don't get stuck on the ball",
        "title_it": 'Tiki-Taka Verticale: non incantarsi sulla palla',
        "content_en": 'The biggest mistake with Vertical Tiki-Taka is to keep possession for too long. The system works precisely BECAUSE the ball gets shot forward quickly after 3-4 short passes. Train the AMC to find the vertical pass.',
        "content_it": "L'errore più comune col Tiki-Taka Verticale è tenere il possesso troppo a lungo. Il sistema funziona proprio PERCHÉ la palla parte in avanti dopo 3-4 passaggi corti. Allena l'AMC a trovare il passaggio verticale."
    },
    {
        "id": '71',
        "category": 'meta',
        "title_en": 'Defensive Counter: pick the counter timing',
        "title_it": 'Defensive Counter: scegli il momento del contropiede',
        "content_en": 'Counter-attack always ON is a beginner mistake. With Defensive Counter you need the SPECIFIC moment: when the opponent commits 2+ players on the same flank. The AMC must read this and trigger the break.',
        "content_it": "Contropiede sempre ON è da principianti. Col Defensive Counter serve il MOMENTO giusto: quando l'avversario sbilancia 2+ giocatori dalla stessa fascia. L'AMC deve leggere e lanciare la ripartenza."
    },
    {
        "id": '72',
        "category": 'meta',
        "title_en": '4-3-3 Tuned: the DMC must be a Playmaker',
        "title_it": '4-3-3 Tuned: il DMC deve essere un Regista',
        "content_en": "The difference between an 'average' 4-3-3 and a 'tuned' 4-3-3 is the DMC. Without a Playmaker ability and Creativity 95+, the tactic collapses to ordinary. Invest tokens here, not on the wingers.",
        "content_it": "La differenza tra un 4-3-3 'normale' e un 4-3-3 'tuned' è il DMC. Senza abilità Regista e Creatività 95+, la tattica crolla in ordinaria. Investi token qui, non sulle ali."
    },
    {
        "id": '73',
        "category": 'meta',
        "title_en": '3-4-3 Press: stamina is the enemy',
        "title_it": '3-4-3 Press: la stamina è il nemico',
        "content_en": "The 3-4-3 Press burns fitness like nothing else. Make 2-3 substitutions by minute 60 and always rotate the ML/MR. Don't use it in three matches in a row: you'll lose the third for sure.",
        "content_it": 'Il 3-4-3 Press brucia condizione come nessun altro modulo. Fai 2-3 cambi entro il 60° e ruota sempre ML/MR. Non usarlo in tre partite consecutive: la terza la perdi di sicuro.'
    },
    {
        "id": '74',
        "category": 'meta',
        "title_en": 'Monster 4-2-3-1: only against weaker teams',
        "title_it": 'Monster 4-2-3-1: solo contro avversari più deboli',
        "content_en": 'The Monster is a no-defense tactic. Against teams within 0.5 stars of yours it WORKS; against stronger ones it ends 5-0 against you. Read the opponent rating BEFORE choosing it.',
        "content_it": 'Il Monster è una tattica senza difesa. Contro avversari entro 0.5 stelle dal tuo livello FUNZIONA; contro più forti finisce 5-0 per loro. Leggi sempre il rating avversario PRIMA di sceglierlo.'
    },
    {
        "id": '75',
        "category": 'meta',
        "title_en": '4-3-3: the absolute meta of the matrix',
        "title_it": '4-3-3: il meta assoluto della matrice',
        "content_en": 'Statistical analysis of 117 matchups: the 4-3-3 beats 26 different modules — almost half of the entire formation database. If you have to learn ONE single formation, learn this one.',
        "content_it": 'Analisi statistica di 117 matchup: il 4-3-3 batte 26 moduli diversi — quasi metà del database completo. Se devi imparare UN solo modulo, impara questo.'
    },
    {
        "id": '76',
        "category": 'meta',
        "title_en": "4-1-4-1: the 'always works' shield",
        "title_it": '4-1-4-1: lo scudo che funziona sempre',
        "content_en": 'Second only to 4-3-3: counters 21/56 modules. Ideal for those who like to defend low. If the opponent loves wing play, switch to 4-1-4-1 and your back four absorbs everything.',
        "content_it": "Secondo solo al 4-3-3: contrasta 21/56 moduli. Ideale per chi ama difendere basso. Se l'avversario gioca tutto sulle fasce, passa al 4-1-4-1 e la tua difesa a 4 assorbe tutto."
    },
    {
        "id": '77',
        "category": 'meta',
        "title_en": '3-4-3 Press: the third choice',
        "title_it": '3-4-3 Press: la terza scelta',
        "content_en": 'Counters 18/56 modules. The 3-4-3 is the most aggressive option in the trio of top-3 effective formations. Pick it when you NEED to score, knowing the back three is exposed.',
        "content_it": 'Contrasta 18/56 moduli. Il 3-4-3 è la scelta più aggressiva del trio dei top-3 efficaci. Sceglilo quando DEVI segnare, accettando che la difesa a 3 sia esposta.'
    },
    {
        "id": '78',
        "category": 'meta',
        "title_en": 'Avoid 4-2-3-1 without a real DMC',
        "title_it": 'Evita 4-2-3-1 senza un DMC vero',
        "content_en": 'The 4-2-3-1 is among the most VULNERABLE: 3+ formations beat it. The reason? Without a creative DMC the playmaker AMC gets isolated. Build the squad spine first.',
        "content_it": "Il 4-2-3-1 è tra i più VULNERABILI: 3+ formazioni lo battono. Il motivo? Senza un DMC creativo, l'AMC playmaker resta isolato. Costruisci prima la colonna vertebrale."
    },
    {
        "id": '79',
        "category": 'meta',
        "title_en": '5-4-1 Flat: not just defense',
        "title_it": '5-4-1 Flat: non solo difesa',
        "content_en": "The 5-4-1 batters 15/56 modules: it's the 4th counter formation in the matrix. Don't think it's only 'park-the-bus' — it's an actual answer to many attacking opponents.",
        "content_it": "Il 5-4-1 contrasta 15/56 moduli: è la 4ª formazione counter della matrice. Non pensare sia solo 'park-the-bus' — è una vera risposta a molti avversari offensivi."
    },
    {
        "id": '80',
        "category": 'meta',
        "title_en": 'Three-CB formations: a balanced choice',
        "title_it": 'Difese a tre: scelta bilanciata',
        "content_en": '20 of the 56 formations use 3 CBs. They beat as many modules as 4-CB ones but are MORE vulnerable to wide play. Use them only with very mobile wing-backs.',
        "content_it": '20 delle 56 formazioni usano 3 DC. Battono tanti moduli quanto quelle a 4 difensori ma sono PIÙ vulnerabili al gioco esterno. Usale solo se hai esterni molto mobili.'
    },
    {
        "id": '81',
        "category": 'meta',
        "title_en": 'Counter philosophy: 3 levels matter',
        "title_it": 'Filosofia del counter: contano 3 livelli',
        "content_en": 'The matrix shows EVERY opponent has 3 counters: offensive, neutral, defensive. The cardinal sin is to always play offensive. Switch based on the rating gap with the opponent.',
        "content_it": "La matrice mostra: OGNI avversario ha 3 counter (offensivo/neutro/difensivo). Il peccato cardinale è giocare sempre offensivo. Cambia in base al gap di rating con l'avversario."
    },
    {
        "id": '82',
        "category": 'meta',
        "title_en": "Read your opponent's defense first",
        "title_it": 'Prima leggi la difesa avversaria',
        "content_en": "Look at the opponent's formation: how many defenders? 3, 4 or 5? This is the FIRST question. Against 3-back you press the flanks; against 5-back you crowd the center.",
        "content_it": 'Guarda la formazione avversaria: quanti difensori? 3, 4 o 5? È la PRIMA domanda. Contro difesa a 3 pressi le fasce; contro difesa a 5 affolli il centro.'
    }
]

# ==================== PLAYER ROLES DATA ====================

PLAYER_ROLES = [
    {
        "id": 'sweeper-keeper',
        "position": 'GK',
        "name_en": 'Sweeper Keeper',
        "name_it": 'Portiere Libero',
        "key_attributes_en": ['Reflexes', 'Aerial Ability', 'Positioning'],
        "key_attributes_it": ['Riflessi', 'Uscite', 'Posizionamento'],
        "best_formations": ['4-5-1', '4-3-3'],
        "training_focus_en": 'Saving, Reflexes, Aerial Ability',
        "training_focus_it": 'Parata, Riflessi, Uscite',
        "description_en": 'Participates in build-up and covers the space behind a high defensive line.',
        "description_it": 'Partecipa alla manovra e copre lo spazio dietro la difesa alta.'
    },
    {
        "id": 'ball-playing-defender',
        "position": 'DC',
        "name_en": 'Ball-Playing Defender',
        "name_it": 'Difensore Regista',
        "key_attributes_en": ['Passing', 'Marking', 'Creativity'],
        "key_attributes_it": ['Passaggio', 'Marcatura', 'Creatività'],
        "best_formations": ['3-5-2', '4-3-3'],
        "training_focus_en": 'Passing, Marking, Positioning',
        "training_focus_it": 'Passaggio, Marcatura, Posizionamento',
        "description_en": 'Essential for clean ball progression under opponent pressing.',
        "description_it": "Fondamentale per l'uscita pulita del pallone sotto pressing avversario."
    },
    {
        "id": 'no-nonsense-centre-back',
        "position": 'DC',
        "name_en": 'No-Nonsense Centre-Back',
        "name_it": 'Difensore Puro',
        "key_attributes_en": ['Tackling', 'Marking', 'Strength'],
        "key_attributes_it": ['Contrasto', 'Marcatura', 'Forza'],
        "best_formations": ['4-4-2', '5-4-1'],
        "training_focus_en": 'Strength, Marking, Tackling',
        "training_focus_it": 'Forza, Marcatura, Contrasto',
        "description_en": 'Focuses purely on defending without risking difficult passes.',
        "description_it": 'Si concentra solo sulla difesa senza rischiare passaggi difficili.'
    },
    {
        "id": 'full-back',
        "position": 'DL/DR',
        "name_en": 'Full-Back',
        "name_it": 'Terzino',
        "key_attributes_en": ['Tackling', 'Marking', 'Pace'],
        "key_attributes_it": ['Contrasto', 'Marcatura', 'Velocità'],
        "best_formations": ['4-1-2-1-2 ND', '4-4-2'],
        "training_focus_en": 'Tackling, Marking, Positioning',
        "training_focus_it": 'Contrasto, Marcatura, Posizionamento',
        "description_en": 'Provides defensive solidity on the flanks against strong opposing wingers.',
        "description_it": 'Garantisce solidità difensiva sulle fasce contro ali avversarie forti.'
    },
    {
        "id": 'wing-back',
        "position": 'DL/DR',
        "name_en": 'Wing-Back',
        "name_it": 'Terzino Fluidificante',
        "key_attributes_en": ['Crossing', 'Pace', 'Tackling'],
        "key_attributes_it": ['Cross', 'Velocità', 'Contrasto'],
        "best_formations": ['3-5-2', '4-5-1 V-Style'],
        "training_focus_en": 'Crossing, Pace, Tackling',
        "training_focus_it": 'Cross, Velocità, Contrasto',
        "description_en": 'Pushes up with a forward arrow to give width and cross for the strikers.',
        "description_it": 'Spinge con freccia SU per dare ampiezza e crossare per le punte.'
    },
    {
        "id": 'inverted-wing-back',
        "position": 'DL/DR',
        "name_en": 'Inverted Wing-Back',
        "name_it": 'Terzino Invertito',
        "key_attributes_en": ['Passing', 'Tackling', 'Positioning'],
        "key_attributes_it": ['Passaggio', 'Contrasto', 'Posizionamento'],
        "best_formations": ['4-3-3', '4-1-4-1'],
        "training_focus_en": 'Passing, Tackling, Dribbling',
        "training_focus_it": 'Passaggio, Contrasto, Dribbling',
        "description_en": 'Tucks into midfield to help control central possession.',
        "description_it": 'Entra in mezzo al campo per aiutare la gestione del possesso centrale.'
    },
    {
        "id": 'anchor-man',
        "position": 'DMC',
        "name_en": 'Anchor Man',
        "name_it": 'Incontrista Arretrato',
        "key_attributes_en": ['Tackling', 'Positioning', 'Strength'],
        "key_attributes_it": ['Contrasto', 'Posizionamento', 'Forza'],
        "best_formations": ['4-1-4-1', '4-5-1 V-Style'],
        "training_focus_en": 'Tackling, Marking, Positioning',
        "training_focus_it": 'Contrasto, Marcatura, Posizionamento',
        "description_en": "The 'advanced stopper' vital to shield the defense and earn clean sheets.",
        "description_it": "Lo 'stopper avanzato' vitale per proteggere la difesa e fare clean sheet."
    },
    {
        "id": 'deep-lying-playmaker',
        "position": 'DMC',
        "name_en": 'Deep-Lying Playmaker',
        "name_it": 'Regista Arretrato',
        "key_attributes_en": ['Passing', 'Creativity', 'Tackling'],
        "key_attributes_it": ['Passaggio', 'Creatività', 'Contrasto'],
        "best_formations": ['4-3-3', '4-1-2-1-2 ND'],
        "training_focus_en": 'Passing, Creativity, Tackling',
        "training_focus_it": 'Passaggio, Creatività, Contrasto',
        "description_en": 'Deep playmaker who distributes the ball and builds play from the back.',
        "description_it": 'Playmaker basso che smista palloni e costruisce gioco dalle retrovie.'
    },
    {
        "id": 'box-to-box-midfielder',
        "position": 'MC',
        "name_en": 'Box-to-Box Midfielder',
        "name_it": 'Centrocampista Totale',
        "key_attributes_en": ['Stamina', 'Passing', 'Tackling'],
        "key_attributes_it": ['Resistenza', 'Passaggio', 'Contrasto'],
        "best_formations": ['4-4-2', '4-5-1 Flat'],
        "training_focus_en": 'Passing, Strength, Stamina',
        "training_focus_it": 'Passaggio, Forza, Resistenza',
        "description_en": 'Tireless midfield engine operating between both penalty boxes.',
        "description_it": 'Instancabile motore del centrocampo che agisce tra le due aree di rigore.'
    },
    {
        "id": 'mezzala',
        "position": 'MC',
        "name_en": 'Mezzala',
        "name_it": 'Mezzala',
        "key_attributes_en": ['Shooting', 'Pace', 'Dribbling'],
        "key_attributes_it": ['Tiro', 'Velocità', 'Dribbling'],
        "best_formations": ['4-3-3', '4-1-3-1-1'],
        "training_focus_en": 'Shooting, Pace, Finishing',
        "training_focus_it": 'Tiro, Velocità, Finalizzazione',
        "description_en": 'Late-running forward who attacks the half-spaces to finish in the box.',
        "description_it": "Incursore che attacca gli half-spaces per concludere l'azione in porta."
    },
    {
        "id": 'advanced-playmaker',
        "position": 'AMC',
        "name_en": 'Advanced Playmaker',
        "name_it": 'Regista Avanzato',
        "key_attributes_en": ['Creativity', 'Passing', 'Shooting'],
        "key_attributes_it": ['Creatività', 'Passaggio', 'Tiro'],
        "best_formations": ['4-2-3-1', '3-4-1-2'],
        "training_focus_en": 'Passing, Creativity, Shooting',
        "training_focus_it": 'Passaggio, Creatività, Tiro',
        "description_en": 'The creative hub who delivers killer assists between the lines.',
        "description_it": 'Il faro della manovra offensiva che serve assist letali tra le linee.'
    },
    {
        "id": 'wide-midfielder',
        "position": 'ML/MR',
        "name_en": 'Wide Midfielder',
        "name_it": 'Esterno di Centrocampo',
        "key_attributes_en": ['Crossing', 'Passing', 'Stamina'],
        "key_attributes_it": ['Cross', 'Passaggio', 'Resistenza'],
        "best_formations": ['4-4-2', '4-5-1 Flat'],
        "training_focus_en": 'Crossing, Passing, Marking',
        "training_focus_it": 'Cross, Passaggio, Marcatura',
        "description_en": 'Provides balance and a constant supply for the strikers.',
        "description_it": 'Garantisce equilibrio e rifornimenti costanti per gli attaccanti.'
    },
    {
        "id": 'classic-winger',
        "position": 'AML/AMR',
        "name_en": 'Classic Winger',
        "name_it": 'Ala Classica',
        "key_attributes_en": ['Crossing', 'Pace', 'Dribbling'],
        "key_attributes_it": ['Cross', 'Velocità', 'Dribbling'],
        "best_formations": ['4-3-3', '4-5-1 V-Style'],
        "training_focus_en": 'Crossing, Pace, Dribbling',
        "training_focus_it": 'Cross, Velocità, Dribbling',
        "description_en": 'Exploits the Dual Position Advantage to beat his man and cross.',
        "description_it": "Sfrutta il Dual Position Advantage per saltare l'uomo e crossare."
    },
    {
        "id": 'inverted-winger',
        "position": 'AML/AMR',
        "name_en": 'Inverted Winger',
        "name_it": 'Ala Invertita',
        "key_attributes_en": ['Shooting', 'Dribbling', 'Pace'],
        "key_attributes_it": ['Tiro', 'Dribbling', 'Velocità'],
        "best_formations": ['4-2-3-1', '4-3-3'],
        "training_focus_en": 'Shooting, Finishing, Dribbling',
        "training_focus_it": 'Tiro, Finalizzazione, Dribbling',
        "description_en": 'Cuts inside to shoot with his inverted foot toward goal.',
        "description_it": 'Taglia verso il centro per calciare col piede invertito verso la porta.'
    },
    {
        "id": 'target-man',
        "position": 'ST',
        "name_en": 'Target Man',
        "name_it": 'Centravanti Boa',
        "key_attributes_en": ['Heading', 'Strength', 'Finishing'],
        "key_attributes_it": ['Colpo di testa', 'Forza', 'Finalizzazione'],
        "best_formations": ['4-4-2', '4-5-1 Flat'],
        "training_focus_en": 'Heading, Strength, Finishing',
        "training_focus_it": 'Colpo di testa, Forza, Finalizzazione',
        "description_en": 'Physical reference for crosses; wins aerial duels against defenders.',
        "description_it": 'Riferimento fisico per i cross; vince i duelli aerei contro i difensori.'
    },
    {
        "id": 'poacher',
        "position": 'ST',
        "name_en": 'Poacher',
        "name_it": "Uomo d'Area",
        "key_attributes_en": ['Finishing', 'Anticipation', 'Shooting'],
        "key_attributes_it": ['Finalizzazione', 'Riflessi', 'Tiro'],
        "best_formations": ['4-1-2-1-2 ND', '3-5-2'],
        "training_focus_en": 'Finishing, Shooting, Pace',
        "training_focus_it": 'Finalizzazione, Tiro, Velocità',
        "description_en": 'Lethal in the final yards, always in the right place at the right time.',
        "description_it": 'Letale negli ultimi metri, si fa trovare sempre al posto giusto.'
    },
    {
        "id": 'complete-forward',
        "position": 'ST',
        "name_en": 'Complete Forward',
        "name_it": 'Attaccante Completo',
        "key_attributes_en": ['Finishing', 'Shooting', 'Passing'],
        "key_attributes_it": ['Finalizzazione', 'Tiro', 'Passaggio'],
        "best_formations": ['4-3-3', '4-4-2'],
        "training_focus_en": 'Finishing, Shooting, Heading',
        "training_focus_it": 'Finalizzazione, Tiro, Colpo di testa',
        "description_en": 'Universal player able to score, assist and hold up the ball.',
        "description_it": 'Giocatore universale capace di segnare, assistere e proteggere palla.'
    },
    {
        "id": 'false-9',
        "position": 'ST',
        "name_en": 'False 9',
        "name_it": 'Falso Nove',
        "key_attributes_en": ['Passing', 'Shooting', 'Creativity'],
        "key_attributes_it": ['Passaggio', 'Tiro', 'Creatività'],
        "best_formations": ['4-5-1 V-Style', '4-3-3'],
        "training_focus_en": 'Passing, Shooting, Creativity',
        "training_focus_it": 'Passaggio, Tiro, Creatività',
        "description_en": 'Strongest playstyle of the 2026 meta: drops deep to free up runners.',
        "description_it": 'Playstyle più forte del meta 2026: si abbassa per liberare inserimenti.'
    },
    {
        "id": 'pressing-forward',
        "position": 'ST',
        "name_en": 'Pressing Forward',
        "name_it": 'Attaccante di Pressing',
        "key_attributes_en": ['Stamina', 'Pace', 'Tackling'],
        "key_attributes_it": ['Resistenza', 'Velocità', 'Contrasto'],
        "best_formations": ['4-1-4-1', '4-3-3'],
        "training_focus_en": 'Pace, Strength, Stamina',
        "training_focus_it": 'Velocità, Forza, Resistenza',
        "description_en": "The team's first defender; harasses defenders during build-up.",
        "description_it": 'Primo difensore della squadra; aggredisce i difensori in costruzione.'
    },
    {
        "id": 'trequartista',
        "position": 'AMC',
        "name_en": 'Trequartista',
        "name_it": 'Trequartista',
        "key_attributes_en": ['Creativity', 'Passing', 'Vision'],
        "key_attributes_it": ['Creativita', 'Passaggio', 'Visione'],
        "best_formations": ['4-3-1-2', '3-4-1-2'],
        "training_focus_en": 'Creativity, Passing, Shooting',
        "training_focus_it": 'Creativita, Passaggio, Tiro',
        "description_en": 'Italian-style #10: stays high and central, drops between the lines to find the killer pass.',
        "description_it": "Il numero 10 all'italiana: alto e centrale, si abbassa tra le linee per trovare il passaggio decisivo."
    },
    {
        "id": 'regista',
        "position": 'DMC',
        "name_en": 'Regista',
        "name_it": 'Regista',
        "key_attributes_en": ['Passing', 'Creativity', 'Vision'],
        "key_attributes_it": ['Passaggio', 'Creativita', 'Visione'],
        "best_formations": ['4-3-3', '4-1-2-1-2 ND'],
        "training_focus_en": 'Passing, Creativity, Long-range Passing',
        "training_focus_it": 'Passaggio, Creativita, Lanci lunghi',
        "description_en": 'The Pirlo role: deep playmaker who orchestrates from in front of the defense.',
        "description_it": 'Il ruolo alla Pirlo: regista basso che orchestra il gioco davanti alla difesa.'
    },
    {
        "id": 'half-back',
        "position": 'DMC',
        "name_en": 'Half-Back',
        "name_it": 'Mediano Arretrato',
        "key_attributes_en": ['Tackling', 'Positioning', 'Passing'],
        "key_attributes_it": ['Contrasto', 'Posizionamento', 'Passaggio'],
        "best_formations": ['3-4-3', '3-5-2'],
        "training_focus_en": 'Tackling, Marking, Positioning',
        "training_focus_it": 'Contrasto, Marcatura, Posizionamento',
        "description_en": 'Drops between the two CBs to form a back three in possession. Modern pivot.',
        "description_it": 'Si abbassa tra i due DC per formare una difesa a tre in fase di possesso. Mediano moderno.'
    },
    {
        "id": 'carrilero',
        "position": 'MC',
        "name_en": 'Carrilero',
        "name_it": 'Carrilero',
        "key_attributes_en": ['Stamina', 'Tackling', 'Positioning'],
        "key_attributes_it": ['Resistenza', 'Contrasto', 'Posizionamento'],
        "best_formations": ['4-4-2', '4-3-3'],
        "training_focus_en": 'Stamina, Tackling, Passing',
        "training_focus_it": 'Resistenza, Contrasto, Passaggio',
        "description_en": 'Spanish-style MC who shuttles between the half-spaces, covers the full-back and supports build-up.',
        "description_it": 'MC alla spagnola che fa la spola sugli half-space, copre il terzino e supporta la manovra.'
    },
    {
        "id": 'raumdeuter',
        "position": 'AML/AMR',
        "name_en": 'Raumdeuter',
        "name_it": 'Raumdeuter',
        "key_attributes_en": ['Anticipation', 'Finishing', 'Off-ball Movement'],
        "key_attributes_it": ['Anticipazione', 'Finalizzazione', 'Smarcamento'],
        "best_formations": ['4-2-3-1', '4-3-3'],
        "training_focus_en": 'Finishing, Anticipation, Positioning',
        "training_focus_it": 'Finalizzazione, Anticipazione, Posizionamento',
        "description_en": "'Space investigator': wide forward who finds and exploits gaps without the ball. Müller's role.",
        "description_it": "'Investigatore degli spazi': ala che trova e sfrutta i varchi senza palla. Il ruolo di Müller."
    },
    {
        "id": 'libero',
        "position": 'DC',
        "name_en": 'Libero',
        "name_it": 'Libero',
        "key_attributes_en": ['Passing', 'Positioning', 'Tackling'],
        "key_attributes_it": ['Passaggio', 'Posizionamento', 'Contrasto'],
        "best_formations": ['3-5-2', '3-4-3'],
        "training_focus_en": 'Passing, Positioning, Marking',
        "training_focus_it": 'Passaggio, Posizionamento, Marcatura',
        "description_en": "Sweeper-CB who steps forward to break the lines. Beckenbauer's role re-imagined.",
        "description_it": 'Difensore centrale libero che esce in conduzione per spezzare le linee. Il ruolo Beckenbauer rivisitato.'
    },
    {
        "id": 'ball-winning-midfielder',
        "position": 'MC',
        "name_en": 'Ball-Winning Midfielder',
        "name_it": 'Centrocampista da Pressing',
        "key_attributes_en": ['Tackling', 'Stamina', 'Aggression'],
        "key_attributes_it": ['Contrasto', 'Resistenza', 'Aggressivita'],
        "best_formations": ['4-3-3', '3-4-3'],
        "training_focus_en": 'Tackling, Stamina, Strength',
        "training_focus_it": 'Contrasto, Resistenza, Forza',
        "description_en": "Aggressive MC dedicated to ball recovery. The 'destroyer' next to the playmaker.",
        "description_it": "MC aggressivo dedicato al recupero palla. Il 'distruttore' accanto al regista."
    },
    {
        "id": 'defensive-forward',
        "position": 'ST',
        "name_en": 'Defensive Forward',
        "name_it": 'Attaccante Difensivo',
        "key_attributes_en": ['Stamina', 'Marking', 'Tackling'],
        "key_attributes_it": ['Resistenza', 'Marcatura', 'Contrasto'],
        "best_formations": ['4-1-4-1', '4-5-1 V-Style'],
        "training_focus_en": 'Stamina, Marking, Anticipation',
        "training_focus_it": 'Resistenza, Marcatura, Anticipazione',
        "description_en": "Striker who drops to mark the opponent's DMC. First defender of the team.",
        "description_it": 'Attaccante che si abbassa per marcare il DMC avversario. Primo difensore della squadra.'
    },
    {
        "id": 'wide-target-man',
        "position": 'AML/AMR',
        "name_en": 'Wide Target Man',
        "name_it": 'Boa Largo',
        "key_attributes_en": ['Heading', 'Strength', 'Crossing'],
        "key_attributes_it": ['Colpo di testa', 'Forza', 'Cross'],
        "best_formations": ['4-3-3', '4-4-2'],
        "training_focus_en": 'Heading, Strength, Crossing',
        "training_focus_it": 'Colpo di testa, Forza, Cross',
        "description_en": 'Physical winger who attacks crosses from the opposite side. Inverted target man.',
        "description_it": "Ala fisica che attacca i cross dal lato opposto. Boa atipico sull'esterno."
    }
]

# ==================== META TACTICS 2026 DATA ====================

META_TACTICS = [
    {
        "id": '4-5-1-v-style',
        "formation": '4-5-1 V-Style',
        "tier": 'S',
        "trending": True,
        "why_it_works_en": 'Considered the most versatile formation of 2026, able to adapt to any opponent.',
        "why_it_works_it": 'Considerata la formazione più versatile del 2026, capace di adattarsi a ogni avversario.',
        "setup_en": 'Normal or defensive mentality, AML/AMR wingers and a DMC vital for defensive cover.',
        "setup_it": 'Mentalità normale o difensiva, ali AML/AMR e un DMC vitale per la copertura difensiva.',
        "counter_en": 'Effectively countered with the 4-3N-3 or the 3N-2-3N-2.',
        "counter_it": 'Si contrasta efficacemente con il 4-3N-3 o il 3N-2-3N-2.'
    },
    {
        "id": '4-3-3',
        "formation": '4-3-3',
        "tier": 'S',
        "trending": True,
        "why_it_works_en": 'Dominates the attacking phase through the lethal synergy between a False Nine and fast wingers.',
        "why_it_works_it": 'Domina la fase offensiva sfruttando la sinergia letale tra False Nine e ali veloci.',
        "setup_en": 'Requires the False Nine playstyle and an attacking mentality with passing focused down the flanks.',
        "setup_it": 'Richiede il playstyle False Nine e mentalità offensiva con focus passaggi sulle fasce.',
        "counter_en": 'Beaten with the 4-4-2 or 4-1-3-1-1 for defensive solidity.',
        "counter_it": 'Si batte con il 4-4-2 o il 4-1-3-1-1 per solidità difensiva.'
    },
    {
        "id": '4-1-2-1-2-nd',
        "formation": '4-1-2-1-2 ND',
        "tier": 'S',
        "trending": True,
        "why_it_works_en": 'Excels at total midfield control and fast ball-carrying transitions.',
        "why_it_works_it": 'Eccelle nel controllo totale del centrocampo e nelle transizioni rapide palla al piede.',
        "setup_en": 'Uses red arrows on the STs and AMC with passing focused strictly through the middle.',
        "setup_it": 'Prevede frecce rosse su ST e AMC con passaggi focalizzati rigorosamente al centro.',
        "counter_en": 'The ideal counter is the 4-5-1 V-Style to stretch the play.',
        "counter_it": 'Il counter ideale è il 4-5-1 V-Style per allargare il gioco.'
    },
    {
        "id": '3-1-5-1',
        "formation": '3-1-5-1',
        "tier": 'A',
        "trending": True,
        "why_it_works_en": "A 'secret' formation that overloads midfield, making the opponent's build-up impossible.",
        "why_it_works_it": "Formazione 'segreta' che sovraccarica la mediana rendendo impossibile la manovra nemica.",
        "setup_en": 'Requires high pressing, an attacking mentality and a solid DMC to screen the back three.',
        "setup_it": 'Richiede pressing alto, mentalità offensiva e un DMC solido per schermare la difesa a tre.',
        "counter_en": 'Countered with direct attacks down the flanks or with the 3-5-2 V.',
        "counter_it": 'Si contrasta con attacchi diretti sulle fasce o con il 3-5-2 V.'
    },
    {
        "id": '4-2-3-1',
        "formation": '4-2-3-1',
        "tier": 'A',
        "trending": False,
        "why_it_works_en": 'Ideal for keeping possession and hurting opposing defenses that lack a DMC.',
        "why_it_works_it": 'Ideale per mantenere il possesso e colpire difese avversarie sprovviste di un DMC.',
        "setup_en": 'Uses an attacking mentality, short passing and a creative AMC to feed the lone striker.',
        "setup_it": "Usa mentalità offensiva, passaggi corti e un AMC creativo per servire l'unica punta.",
        "counter_en": 'The best counter is the 4-1-3N-2 with a deep defensive line.',
        "counter_it": 'Il miglior counter è il 4-1-3N-2 con difesa arretrata.'
    },
    {
        "id": '4-2-2-2-hexagon',
        "formation": '4-2-2-2 Hexagon',
        "tier": 'A',
        "trending": True,
        "why_it_works_en": "A very balanced formation, called 'fashionable' for its excellent pitch coverage.",
        "why_it_works_it": "Formazione molto equilibrata e definita 'di moda' per la sua ottima copertura del campo.",
        "setup_en": 'Uses two DMCs for stability and wide players to supply the two central strikers.',
        "setup_it": 'Utilizza due DMC per la stabilità e ali larghe per rifornire i due attaccanti centrali.',
        "counter_en": 'Countered with the 3-4-3 or the 4-5-1 V-Style.',
        "counter_it": 'Si contrasta con il 3-4-3 o con il 4-5-1 V-Style.'
    },
    {
        "id": '4-1-3-1-1',
        "formation": '4-1-3-1-1',
        "tier": 'B',
        "trending": False,
        "why_it_works_en": 'Provides superior defensive protection, ideal for earning clean sheets.',
        "why_it_works_it": 'Fornisce una protezione difensiva superiore, ideale per ottenere partite a porta inviolata.',
        "setup_en": 'Deploys a deep DMC and MCs to handle strong strikers and midfielders.',
        "setup_it": 'Prevede DMC e MC in posizione arretrata per gestire attaccanti e centrocampisti forti.',
        "counter_en": 'Beaten by formations that overload its MCs, like the 4-5-1 V.',
        "counter_it": 'Si batte usando formazioni che sovraccaricano i suoi MC, come il 4-5-1 V.'
    },
    {
        "id": '4-1-4-1',
        "formation": '4-1-4-1',
        "tier": 'B',
        "trending": False,
        "why_it_works_en": 'An excellent formation to neutralize the opposing midfield and control the tempo.',
        "why_it_works_it": 'Formazione eccellente per neutralizzare il centrocampo avversario e gestire il ritmo.',
        "setup_en": 'Requires a defensive/normal mentality and a DMC with a blue arrow to close every gap.',
        "setup_it": 'Richiede mentalità difensiva/normale e un DMC con freccia blu per chiudere ogni spazio.',
        "counter_en": 'Beaten with the 4-2-2-2 Hexagon to break its rigidity.',
        "counter_it": 'Si batte con il 4-2-2-2 Hexagon per spezzare la sua rigidità.'
    },
    {
        "id": '4-2-3-1-vertical-tiki-taka',
        "formation": '4-2-3-1 Vertical Tiki-Taka',
        "tier": 'S',
        "trending": True,
        "why_it_works_en": 'Combines short possession with quick vertical bursts: dominates the ball without losing pace in attack.',
        "why_it_works_it": 'Combina possesso corto con verticalizzazioni rapide: domina la palla senza perdere ritmo in attacco.',
        "setup_en": 'Attacking mentality, short passing through the middle, AMC as creator, AML/AMR cutting inside on red arrows.',
        "setup_it": 'Mentalità offensiva, passaggi corti al centro, AMC creatore, AML/AMR che rientrano con freccia rossa.',
        "counter_en": 'Beaten with a 4-1-3-1-1 that crowds the AMC and blocks vertical lanes.',
        "counter_it": "Si batte col 4-1-3-1-1 che soffoca l'AMC e blocca le linee verticali."
    },
    {
        "id": '4-2-3-1-defensive-counter',
        "formation": '4-2-3-1 Defensive Counter',
        "tier": 'A',
        "trending": True,
        "why_it_works_en": 'Defensive shape with two MCs protecting the back four, then exploding on the counter through the AMC and wingers.',
        "why_it_works_it": 'Modulo difensivo con doppio MC a proteggere la difesa, poi esplode in contropiede con AMC e ali.',
        "setup_en": 'Defensive mentality, mixed passing, low pressing, counter-attack ON, blue arrows on the back line and MCs, red on AMC.',
        "setup_it": 'Mentalità difensiva, passaggi misti, pressing basso, contropiede ON, frecce blu su difesa e MC, rossa su AMC.',
        "counter_en": 'Hard Attacking with a 3-4-3 that presses high and limits the time to organize the counter.',
        "counter_it": "Molto Offensivo col 3-4-3 che pressa alto e toglie tempo all'organizzazione del contropiede."
    },
    {
        "id": '4-3-3-tuned-meta',
        "formation": '4-3-3 Tuned Meta',
        "tier": 'S',
        "trending": True,
        "why_it_works_en": "Optimized variant of the 4-3-3: false 9, two box-to-box MCs, deep playmaker DMC. The 'tuned' setup of the current meta.",
        "why_it_works_it": "Variante ottimizzata del 4-3-3: falso 9, due MC box-to-box, regista basso DMC. Il setup 'tuned' del meta attuale.",
        "setup_en": 'Attacking mentality, short passing down both flanks, high pressing, the DMC has Playmaker ability, both MCs Box-to-Box, ST False 9.',
        "setup_it": 'Mentalità offensiva, passaggi corti sulle fasce, pressing alto, DMC con abilità Regista, entrambi i MC Box-to-Box, ST Falso 9.',
        "counter_en": 'Defensive 4-1-3-1-1: a DMC and an MC sit deep, marking the False 9 closely.',
        "counter_it": '4-1-3-1-1 difensivo: DMC e un MC arretrati, marcatura stretta sul Falso 9.'
    },
    {
        "id": '3-4-3-press',
        "formation": '3-4-3 Press',
        "tier": 'A',
        "trending": True,
        "why_it_works_en": 'Three-CB stability + four midfield workers + three forwards on red arrows. Gegenpressing in Top Eleven style.',
        "why_it_works_it": 'Stabilità a 3 DC + quattro centrocampisti operai + tridente con freccia rossa. Gegenpressing in stile Top Eleven.',
        "setup_en": 'Hard Attacking, high pressing, hard tackling, man-to-man marking, red arrows on the front three and on the wide MCs (ML/MR).',
        "setup_it": 'Molto Offensivo, pressing alto, contrasti duri, marcatura a uomo, frecce rosse sul tridente e sui MC larghi (ML/MR).',
        "counter_en": 'Defensive 4-1-4-1 that absorbs pressure and counters down the wings.',
        "counter_it": '4-1-4-1 difensivo che assorbe la pressione e riparte sulle fasce.'
    },
    {
        "id": '4-2-3-1-monster',
        "formation": '4-2-3-1 Monster',
        "tier": 'S',
        "trending": True,
        "why_it_works_en": 'Ultra-aggressive 4-2-3-1 designed to score 3+ goals per match. Sacrifices defensive cover for total attacking dominance.',
        "why_it_works_it": '4-2-3-1 ultra-aggressivo per segnare 3+ gol a partita. Sacrifica copertura difensiva per dominio totale in attacco.',
        "setup_en": 'Hard Attacking mentality, short passing through the middle, high pressing, hard tackling, all the attacking line on red arrows.',
        "setup_it": "Mentalità Molto Offensiva, passaggi corti al centro, pressing alto, contrasti duri, tutto l'attacco con freccia rossa.",
        "counter_en": '5-3-2 with offside trap ON: park the bus and exploit the empty back when they over-commit.',
        "counter_it": "5-3-2 con fuorigioco ON: parcheggia l'autobus e sfrutta le spalle scoperte quando si sbilanciano."
    }
]


# ==================== ABBREVIATIONS LEGEND ====================
# Leggenda delle abbreviazioni dei moduli Top Eleven

ABBREVIATIONS = [
    {
        "code": "F",
        "name_en": "Flat",
        "name_it": "Piatto",
        "example": "4-4-2 F",
        "description_en": "All midfielders or defenders on a flat line, no diagonal.",
        "description_it": "Tutti i centrocampisti o difensori su una linea piatta, senza diagonale."
    },
    {
        "code": "N",
        "name_en": "Narrow",
        "name_it": "Stretto",
        "example": "3N-5-2",
        "description_en": "Central positioning, no full-backs or wide midfielders.",
        "description_it": "Posizionamento centrale, senza terzini o esterni di centrocampo."
    },
    {
        "code": "W",
        "name_en": "Wide",
        "name_it": "Largo",
        "example": "3W-4-3",
        "description_en": "Players positioned on the flanks: full-backs/wing-backs and wide midfielders.",
        "description_it": "Giocatori posizionati sulle fasce: terzini/esterni e centrocampisti larghi."
    },
    {
        "code": "B",
        "name_en": "Butterfly",
        "name_it": "Farfalla",
        "example": "3N-2W-2N-2W-1",
        "description_en": "Butterfly shape with alternating narrow/wide lines.",
        "description_it": "Forma a farfalla con linee alternate strette/larghe."
    },
    {
        "code": "C",
        "name_en": "Curved",
        "name_it": "Curvo",
        "example": "3 DC + DL/DR avanzati",
        "description_en": "Three CBs with advanced full-backs forming a curved defensive line.",
        "description_it": "Tre DC con terzini avanzati che formano una linea difensiva curva."
    },
    {
        "code": "D",
        "name_en": "Dandelion",
        "name_it": "Dente di Leone",
        "example": "3N-1-3W-1-2",
        "description_en": "Dandelion shape with narrow central base and wide attacking midfield.",
        "description_it": "Forma a dente di leone con base centrale stretta e centrocampo offensivo largo."
    },
    {
        "code": "H",
        "name_en": "Hexagon",
        "name_it": "Esagono",
        "example": "4-0-2N-2W-2",
        "description_en": "Hexagonal shape with central density and wide attacking midfielders.",
        "description_it": "Forma esagonale con densita centrale e trequartisti larghi."
    },
    {
        "code": "V",
        "name_en": "V-Style",
        "name_it": "Stile V",
        "example": "4-[1-2N-2W]-1",
        "description_en": "V-shape midfield with DMC anchor, central MCs and high AML/AMR.",
        "description_it": "Centrocampo a V con DMC ancora, MC al centro e AML/AMR alti."
    },
    {
        "code": "ET",
        "name_en": "Eiffel Tower",
        "name_it": "Torre Eiffel",
        "example": "3-2N-3-1-1",
        "description_en": "Tower-shaped formation: narrow at the top, wide at the base.",
        "description_it": "Formazione a torre, stretta in alto e larga alla base."
    },
    {
        "code": "ML",
        "name_en": "Maple Leaf",
        "name_it": "Foglia d'Acero",
        "example": "3W-2N-3W-1-1",
        "description_en": "Maple Leaf shape: wide base, narrow midfield core, wide attack.",
        "description_it": "Forma a foglia d'acero: base larga, centro stretto, attacco largo."
    },
    {
        "code": "ND",
        "name_en": "Narrow Diamond",
        "name_it": "Diamante Stretto",
        "example": "4-1-2N-1-2",
        "description_en": "Diamond midfield centered: DMC, two narrow MCs, AMC.",
        "description_it": "Diamante centrale: DMC, due MC stretti, AMC."
    },
    {
        "code": "WD",
        "name_en": "Wide Diamond",
        "name_it": "Diamante Largo",
        "example": "4-1-2W-1-2",
        "description_en": "Diamond midfield with two wide MCs (ML/MR) and AMC.",
        "description_it": "Diamante con due MC larghi (ML/MR) e AMC."
    },
    {
        "code": "XT",
        "name_en": "Xmas Tree",
        "name_it": "Albero di Natale",
        "example": "4-0-3W-2N-1",
        "description_en": "Christmas tree shape: 4 defenders, no DMC, 3 wide MCs, 2 narrow AMCs, 1 ST.",
        "description_it": "Albero di Natale: 4 difensori, no DMC, 3 MC larghi, 2 AMC stretti, 1 punta."
    }
]

# ==================== SPECIAL ABILITIES DATA ====================

SPECIAL_ABILITIES = [
    {
        "id": 'shadow-striker',
        "name_en": 'Shadow Striker',
        "name_it": 'Incursore Ombra',
        "best_role": 'AMC',
        "effect_en": 'Lets the player break into empty spaces to score.',
        "effect_it": 'Permette al giocatore di inserirsi negli spazi vuoti per segnare.',
        "when_to_use_en": "Use against opponents who don't field a DMC to protect the defense.",
        "when_to_use_it": 'Da usare contro avversari che non utilizzano un DMC per proteggere la difesa.'
    },
    {
        "id": 'playmaker',
        "name_en": 'Playmaker',
        "name_it": 'Regista',
        "best_role": 'MC, AMC, DMC',
        "effect_en": 'Improves vision and the accuracy of decisive passes.',
        "effect_it": 'Migliora la visione di gioco e la precisione dei passaggi decisivi.',
        "when_to_use_en": 'Key to dominating possession and providing assists between the lines.',
        "when_to_use_it": 'Fondamentale per dominare il possesso palla e servire assist tra le linee.'
    },
    {
        "id": 'dual-position',
        "name_en": 'Dual Position',
        "name_it": 'Ruolo Doppio',
        "best_role": 'Ogni ruolo',
        "effect_en": 'Allows the player to perform at full effectiveness in multiple positions.',
        "effect_it": 'Consente al giocatore di agire con massima efficacia in più posizioni.',
        "when_to_use_en": "For tactical flexibility and to exploit the opponent's formation weaknesses.",
        "when_to_use_it": 'Per avere flessibilità tattica e colpire i punti deboli della formazione avversaria.'
    },
    {
        "id": 'free-kick-specialist',
        "name_en": 'Free Kick Specialist',
        "name_it": 'Specialista Punizioni',
        "best_role": 'ST, AMC, MC',
        "effect_en": 'Drastically increases the chance of scoring from direct free kicks.',
        "effect_it": 'Aumenta drasticamente la probabilità di segnare su calcio di punizione diretto.',
        "when_to_use_en": 'Essential to unlock tight matches through set pieces.',
        "when_to_use_it": 'Essenziale per sbloccare partite chiuse tramite situazioni di palla inattiva.'
    },
    {
        "id": 'corner-specialist',
        "name_en": 'Corner Specialist',
        "name_it": 'Specialista Angoli',
        "best_role": 'ML, MR, AML, AMR',
        "effect_en": 'Improves the accuracy and curl of corner deliveries.',
        "effect_it": "Migliora la precisione e l'effetto dei cross effettuati dalla bandierina.",
        "when_to_use_en": 'Useful to maximize the aerial game if you have strong headers in the box.',
        "when_to_use_it": 'Utile per massimizzare il gioco aereo se si dispone di saltatori forti in area.'
    },
    {
        "id": 'penalty-specialist',
        "name_en": 'Penalty Specialist',
        "name_it": 'Specialista Rigori',
        "best_role": 'ST, AMC',
        "effect_en": 'Ensures near-perfect accuracy when converting penalties.',
        "effect_it": 'Garantisce una precisione quasi totale nella trasformazione dei tiri dal dischetto.',
        "when_to_use_en": "Assign to your designated penalty taker so you don't waste spot kicks.",
        "when_to_use_it": 'Da assegnare al rigorista designato per non sprecare occasioni dagli undici metri.'
    },
    {
        "id": 'one-on-one-scoring',
        "name_en": 'One-on-One Scoring',
        "name_it": 'Finalizzatore 1v1',
        "best_role": 'ST, AML, AMR',
        "effect_en": 'Boosts scoring ability when the player faces the keeper one-on-one.',
        "effect_it": 'Potenzia la capacità di segnare quando il giocatore affronta il portiere in solitaria.',
        "when_to_use_en": 'Ideal for fast strikers who often operate on the counter.',
        "when_to_use_it": 'Ideale per attaccanti veloci che agiscono spesso in contropiede.'
    },
    {
        "id": 'defensive-wall',
        "name_en": 'Defensive Wall',
        "name_it": 'Muro Difensivo',
        "best_role": 'DC, DMC',
        "effect_en": 'Increases the chance of blocking or deflecting shots on goal.',
        "effect_it": 'Aumenta la probabilità di intercettare o respingere i tiri avversari diretti in porta.',
        "when_to_use_en": 'To turn your box into a fortress against big shooters.',
        "when_to_use_it": 'Per rendere la propria area di rigore un fortino contro i grandi tiratori.'
    },
    {
        "id": 'aerial-defence',
        "name_en": 'Aerial Defence',
        "name_it": 'Difesa Aerea',
        "best_role": 'DC',
        "effect_en": 'Improves timing and strength in aerial duels inside the box.',
        "effect_it": "Migliora il tempismo e la forza nei contrasti aerei all'interno dell'area.",
        "when_to_use_en": 'Indispensable against opponents using a Target Man or constant crosses.',
        "when_to_use_it": 'Indispensabile contro avversari che utilizzano Target Man o cross continui.'
    },
    {
        "id": 'pacey-dribbler',
        "name_en": 'Pacey Dribbler',
        "name_it": 'Dribblatore Veloce',
        "best_role": 'AML, AMR, ST',
        "effect_en": 'Increases ball control and speed when dribbling at pace.',
        "effect_it": 'Incrementa il controllo palla e la velocità durante i dribbling in progressione.',
        "when_to_use_en": 'To beat your man out wide and create instant numerical advantage.',
        "when_to_use_it": "Per saltare l'uomo sulle fasce e creare superiorità numerica immediata."
    },
    {
        "id": 'long-throw-in',
        "name_en": 'Long Throw-in',
        "name_it": 'Rimessa Lunga',
        "best_role": 'DL, DR',
        "effect_en": 'Allows throwing the ball directly into the box from throw-ins.',
        "effect_it": 'Permette di lanciare la palla direttamente in area durante le rimesse laterali.',
        "when_to_use_en": 'Turns a simple throw-in into a potential scoring chance.',
        "when_to_use_it": 'Trasforma una semplice rimessa laterale in una potenziale occasione da gol.'
    },
    {
        "id": 'ball-magnet',
        "name_en": 'Ball Magnet',
        "name_it": 'Calamita di Palla',
        "best_role": 'MC, AMC, DMC',
        "effect_en": 'Significantly increases the chance of receiving a pass: opens passing lanes wider than the rest of the team.',
        "effect_it": 'Aumenta significativamente la probabilità di ricevere un passaggio: apre linee di passaggio più larghe del resto della squadra.',
        "when_to_use_en": 'On the team playmaker. Multiplies the effectiveness of a Tiki-Taka system.',
        "when_to_use_it": "Sul regista della squadra. Moltiplica l'efficacia di un sistema Tiki-Taka."
    },
    {
        "id": 'speed-merchant',
        "name_en": 'Speed Merchant',
        "name_it": 'Velocista',
        "best_role": 'AML, AMR, ST',
        "effect_en": 'Adds a real burst of pace in transitions: leaves slower defenders in his wake.',
        "effect_it": 'Aggiunge un vero scatto di velocità nelle transizioni: lascia sul posto i difensori più lenti.',
        "when_to_use_en": 'On the counter-attack winger. Devastating against high defensive lines.',
        "when_to_use_it": "Sull'ala da contropiede. Devastante contro linee difensive alte."
    },
    {
        "id": 'goal-poacher',
        "name_en": 'Goal Poacher',
        "name_it": 'Bomber di Razza',
        "best_role": 'ST',
        "effect_en": 'Extreme finishing ability inside the penalty area, even from difficult angles.',
        "effect_it": "Capacita di finalizzazione estrema dentro l'area, anche da angolazioni difficili.",
        "when_to_use_en": 'On the main striker. Multiplies the conversion rate from chances.',
        "when_to_use_it": "Sull'attaccante centrale. Moltiplica il tasso di conversione delle occasioni."
    },
    {
        "id": 'aerial-threat',
        "name_en": 'Aerial Threat',
        "name_it": 'Forza Aerea',
        "best_role": 'ST, DC',
        "effect_en": 'Dominates aerial duels on corners and crosses, scoring or defending headed balls.',
        "effect_it": 'Domina i duelli aerei su corner e cross, segna o difende di testa.',
        "when_to_use_en": 'Essential for tactics built on crosses or set-piece dominance.',
        "when_to_use_it": 'Indispensabile per tattiche che vivono di cross o di dominio sui calci piazzati.'
    },
    {
        "id": 'set-piece-master',
        "name_en": 'Set-Piece Master',
        "name_it": 'Specialista delle Palle Inattive',
        "best_role": 'MC, AMC',
        "effect_en": 'Combines Free Kick + Corner + Penalty specialist in a single ability. Dead-ball god.',
        "effect_it": 'Combina Punizioni + Angoli + Rigori in una singola abilita. Dio dei calci piazzati.',
        "when_to_use_en": 'Rare and expensive. Saves you 3 player slots dedicated to set pieces.',
        "when_to_use_it": 'Rara e costosa. Ti risparmia 3 slot di giocatori dedicati ai calci piazzati.'
    },
    {
        "id": 'strong-tackler',
        "name_en": 'Strong Tackler',
        "name_it": 'Contrastista',
        "best_role": 'DC, DMC, MC',
        "effect_en": 'Tackles with surgical precision, reducing fouls and gaining the ball cleanly.',
        "effect_it": 'Contrasta con precisione chirurgica, riducendo i falli e guadagnando palla pulita.',
        "when_to_use_en": 'On the midfield destroyer. Allows hard tackling without yellow card risk.',
        "when_to_use_it": 'Sul distruttore di centrocampo. Permette contrasti duri senza rischio cartellino.'
    },
    {
        "id": 'anticipation',
        "name_en": 'Anticipation',
        "name_it": 'Anticipazione',
        "best_role": 'DC, DMC',
        "effect_en": 'Reads opposing passes early, intercepting balls and breaking up attacks before they develop.',
        "effect_it": 'Legge i passaggi avversari in anticipo, intercettando le palle e spezzando gli attacchi sul nascere.',
        "when_to_use_en": 'On the central CB. Worth more than +20% Tackling against creative opponents.',
        "when_to_use_it": 'Sul DC centrale. Vale piu di +20% di Contrasto contro avversari creativi.'
    },
    {
        "id": 'crosser',
        "name_en": 'Crosser',
        "name_it": 'Crossatore',
        "best_role": 'ML, MR, DL, DR',
        "effect_en": 'High-quality crosses with curl and pace, always finding the head of the strikers.',
        "effect_it": 'Cross di alta qualita con effetto e velocita, trovano sempre la testa degli attaccanti.',
        "when_to_use_en": 'On full-backs or wide MCs in formations that play on the flanks.',
        "when_to_use_it": 'Sui terzini o MC larghi nei moduli che giocano sulle fasce.'
    },
    {
        "id": 'wall-pass-master',
        "name_en": 'Wall-Pass Master',
        "name_it": 'Maestro dei Triangoli',
        "best_role": 'MC, AMC',
        "effect_en": 'Specialist in one-twos: launches and receives back the ball quickly to break the lines.',
        "effect_it": 'Specialista del uno-due: rilancia e riceve velocemente per spezzare le linee.',
        "when_to_use_en": 'On the offensive MC. Devastating in possession-based systems.',
        "when_to_use_it": 'Sul MC offensivo. Devastante nei sistemi basati sul possesso.'
    },
    {
        "id": 'long-shot-specialist',
        "name_en": 'Long-Shot Specialist',
        "name_it": 'Specialista Tiro da Fuori',
        "best_role": 'MC, AMC, AML, AMR',
        "effect_en": 'Lethal shots from outside the box, breaking compact and deep defenses.',
        "effect_it": 'Tiri letali da fuori area, scardinano difese compatte e basse.',
        "when_to_use_en": "Against teams that 'park the bus' (5-4-1 Flat, 4-5-1 V-Style defensive).",
        "when_to_use_it": "Contro squadre che 'parcheggiano l'autobus' (5-4-1 Flat, 4-5-1 V difensivo)."
    }
]

# ==================== TRAINING GUIDE DATA ====================

TRAINING_GUIDE = [
    {
        "position": "GK",
        "priority_attributes_en": ["Saving", "Reflexes", "Aerial Ability", "Positioning"],
        "priority_attributes_it": ["Parata", "Riflessi", "Uscite", "Posizionamento"],
        "recommended_drills_en": ["GK Training"],
        "recommended_drills_it": ["Allenamento GK"],
        "note_en": "You can turn 3-star keepers into 10-star superstars with specific training.",
        "note_it": "È possibile trasformare portieri da 3 stelle in superstar da 10 stelle con allenamenti specifici."
    },
    {
        "position": "DC",
        "priority_attributes_en": ["Marking", "Tackling", "Positioning"],
        "priority_attributes_it": ["Marcatura", "Contrasto", "Posizionamento"],
        "recommended_drills_en": ["Press the Play"],
        "recommended_drills_it": ["Pressa il gioco"],
        "note_en": "Train defenders with the 'Press the Play' drill to maximize white defensive attributes.",
        "note_it": "Allena i difensori con il drill 'Pressa il gioco' per massimizzare gli attributi bianchi difensivi."
    },
    {
        "position": "DL/DR",
        "priority_attributes_en": ["Pace", "Tackling", "Marking", "Crossing"],
        "priority_attributes_it": ["Velocità", "Contrasto", "Marcatura", "Cross"],
        "recommended_drills_en": ["Defense", "Wings"],
        "recommended_drills_it": ["Difesa", "Ali"],
        "note_en": "Pace is a key attribute when deciding whether to use tactical arrows on full-backs.",
        "note_it": "La velocità è un attributo chiave per decidere l'uso delle frecce tattiche sui difensori laterali."
    },
    {
        "position": "DMC",
        "priority_attributes_en": ["Tackling", "Marking", "Positioning", "Passing"],
        "priority_attributes_it": ["Contrasto", "Marcatura", "Posizionamento", "Passaggio"],
        "recommended_drills_en": ["Pressing", "Defense"],
        "recommended_drills_it": ["Pressing", "Difesa"],
        "note_en": "The DMC is vital in almost every formation to earn more clean sheets.",
        "note_it": "Il DMC è vitale in quasi ogni modulo per ottenere un maggior numero di clean sheet."
    },
    {
        "position": "MC",
        "priority_attributes_en": ["Passing", "Creativity", "Dribbling", "Stamina"],
        "priority_attributes_it": ["Passaggio", "Creatività", "Dribbling", "Resistenza"],
        "recommended_drills_en": ["Possession"],
        "recommended_drills_it": ["Possesso palla"],
        "note_en": "Central midfielders must balance defense and attack to dominate the middle.",
        "note_it": "I centrocampisti centrali devono bilanciare difesa e attacco per dominare la zona mediana."
    },
    {
        "position": "ML/MR",
        "priority_attributes_en": ["Crossing", "Passing", "Pace", "Dribbling"],
        "priority_attributes_it": ["Cross", "Passaggio", "Velocità", "Dribbling"],
        "recommended_drills_en": ["Wings", "Slalom"],
        "recommended_drills_it": ["Ali", "Slalom"],
        "note_en": "Having wide players with too-low quality (-70%) makes flank-based formations ineffective.",
        "note_it": "Avere esterni con qualità troppo bassa (-70%) rende inefficaci i moduli che sfruttano le fasce."
    },
    {
        "position": "AMC",
        "priority_attributes_en": ["Passing", "Creativity", "Shooting", "Finishing"],
        "priority_attributes_it": ["Passaggio", "Creatività", "Tiro", "Finalizzazione"],
        "recommended_drills_en": ["Attacking Skills", "Creativity"],
        "recommended_drills_it": ["Skill d'attacco", "Creatività"],
        "note_en": "An AMC with high creativity and passing is key to feeding lethal assists to the striker.",
        "note_it": "Un AMC con alta creatività e passaggio è fondamentale per servire assist letali alla punta."
    },
    {
        "position": "AML/AMR",
        "priority_attributes_en": ["Crossing", "Pace", "Finishing", "Passing"],
        "priority_attributes_it": ["Cross", "Velocità", "Finalizzazione", "Passaggio"],
        "recommended_drills_en": ["Fast Counter", "Slalom"],
        "recommended_drills_it": ["Contrattacco veloce", "Slalom"],
        "note_en": "Wingers exploit the 'Dual Position Advantage' to create overloads and cross.",
        "note_it": "Le ali sfruttano il 'Dual Position Advantage' per creare superiorità numerica e crossare."
    },
    {
        "position": "ST",
        "priority_attributes_en": ["Finishing", "Shooting", "Pace", "Dribbling"],
        "priority_attributes_it": ["Finalizzazione", "Tiro", "Velocità", "Dribbling"],
        "recommended_drills_en": ["Finishing", "Attacking Skills"],
        "recommended_drills_it": ["Finalizzazione", "Skill d'attacco"],
        "note_en": "A striker with very high white attributes outperforms one with more stars but high grey stats.",
        "note_it": "Un attaccante con attributi bianchi altissimi performa meglio di uno con più stelle ma statistiche grigie elevate."
    }
]

# ==================== REAL TEAMS DATA (icone tattiche del calcio) ====================

REAL_TEAMS = [
    {
        "id": "pep-city",
        "manager": "Pep Guardiola",
        "team": "Manchester City",
        "era": "2017-oggi",
        "style_en": "Positional play, possession, false 9",
        "style_it": "Gioco di posizione, possesso, falso nove",
        "te_formation": "4-3-3",
        "te_formation_id": "433",
        "key_attributes_en": ["Passing", "Creativity", "Dribbling"],
        "key_attributes_it": ["Passaggio", "Creatività", "Dribbling"],
        "arrows": "DL↑ DR↑ AML↑ AMR↑",
        "mentality": "Attacking",
        "philosophy_en": "Dominate possession, overload the center, attack the half-spaces. The false nine drops between the lines to drag CBs out of position.",
        "philosophy_it": "Dominare il possesso, sovraccaricare il centro, attaccare gli half-spaces. Il falso nove si abbassa tra le linee per portare fuori i DC.",
        "how_to_copy_en": "Use the 4-3-3 with a False Nine striker. Push full-backs high with red arrows. Train MCs in Passing/Creativity. Set short passing through the middle.",
        "how_to_copy_it": "Usa il 4-3-3 con un attaccante Falso Nove. Spingi i terzini in alto con freccia rossa. Allena i MC in Passaggio/Creatività. Passaggi corti al centro."
    },
    {
        "id": "klopp-liverpool",
        "manager": "Jürgen Klopp",
        "team": "Liverpool",
        "era": "2015-2024",
        "style_en": "Gegenpressing, vertical transitions, heavy metal football",
        "style_it": "Gegenpressing, transizioni verticali, calcio aggressivo",
        "te_formation": "4-3-3",
        "te_formation_id": "433",
        "key_attributes_en": ["Stamina", "Pace", "Pressing"],
        "key_attributes_it": ["Resistenza", "Velocità", "Pressing"],
        "arrows": "AML↑ AMR↑ ST↑",
        "mentality": "Hard Attacking",
        "philosophy_en": "Press immediately after losing the ball, win it back in 5 seconds, attack vertically. Fast wide forwards cutting inside; tireless midfielders.",
        "philosophy_it": "Pressing immediato dopo aver perso palla, recupero in 5 secondi, attacco verticale. Ali veloci che rientrano; centrocampisti instancabili.",
        "how_to_copy_en": "4-3-3 with High Pressing, Hard Attacking mentality and counter-attack ON. Wingers with high Pace and Finishing. Box-to-Box MCs with high Stamina.",
        "how_to_copy_it": "4-3-3 con Pressing Alto, mentalità Molto Attaccante e contropiede ON. Ali con Velocità e Finalizzazione alte. MC box-to-box con Resistenza alta."
    },
    {
        "id": "ancelotti-real",
        "manager": "Carlo Ancelotti",
        "team": "Real Madrid",
        "era": "2021-oggi",
        "style_en": "Balanced 4-3-3, individual freedom, ruthless counters",
        "style_it": "4-3-3 equilibrato, libertà individuale, contropiedi letali",
        "te_formation": "4-3-3",
        "te_formation_id": "433",
        "key_attributes_en": ["Finishing", "Pace", "Creativity"],
        "key_attributes_it": ["Finalizzazione", "Velocità", "Creatività"],
        "arrows": "AML↑ AMR↑",
        "mentality": "Normal",
        "philosophy_en": "Less rigid than Pep: give your stars freedom, defend compact in midfield, devastate on the counter with pace and finishing. Champions League DNA.",
        "philosophy_it": "Meno rigido di Pep: dai libertà ai campioni, difendi compatto a centrocampo, devasta in contropiede con velocità e finalizzazione. DNA Champions.",
        "how_to_copy_en": "4-3-3 Normal mentality, counter-attack ON, mixed passing. Don't push full-backs too high. Star strikers must finish chances.",
        "how_to_copy_it": "4-3-3 mentalità Normale, contropiede ON, passaggi misti. Non spingere troppo i terzini. Le punte stelle devono concretizzare."
    },
    {
        "id": "conte-inter",
        "manager": "Antonio Conte",
        "team": "Inter / Tottenham / Juve",
        "era": "2011-oggi",
        "style_en": "3-5-2 with wing-backs, vertical aggression, brutal physicality",
        "style_it": "3-5-2 con esterni fluidificanti, verticalità, fisicità brutale",
        "te_formation": "3-5-2 Flat",
        "te_formation_id": "352f",
        "key_attributes_en": ["Stamina", "Strength", "Crossing"],
        "key_attributes_it": ["Resistenza", "Forza", "Cross"],
        "arrows": "ML↑ MR↑",
        "mentality": "Attacking",
        "philosophy_en": "Three powerful CBs, two wing-backs covering the whole flank, two strikers always present. Direct, vertical, never sterile possession.",
        "philosophy_it": "Tre DC potenti, due esterni che coprono tutta la fascia, due punte sempre presenti. Diretto, verticale, mai possesso sterile.",
        "how_to_copy_en": "3-5-2 with red arrows on ML/MR (wing-backs). Train them in Stamina/Crossing. Long/mixed passing. Strong heading on both strikers.",
        "how_to_copy_it": "3-5-2 con freccia rossa su ML/MR (esterni). Allena Resistenza/Cross. Passaggi lunghi/misti. Colpo di testa forte su entrambi gli attaccanti."
    },
    {
        "id": "mourinho-inter-2010",
        "manager": "José Mourinho",
        "team": "Inter Triplete",
        "era": "2009-2010",
        "style_en": "Pragmatic defense, lethal counters, total tactical discipline",
        "style_it": "Difesa pragmatica, contropiedi letali, disciplina tattica totale",
        "te_formation": "4-2-3-1",
        "te_formation_id": "4231",
        "key_attributes_en": ["Tackling", "Marking", "Pace"],
        "key_attributes_it": ["Contrasto", "Marcatura", "Velocità"],
        "arrows": "DL↓ DC↓ DR↓ MC↓ AML↑ AMR↑",
        "mentality": "Defensive",
        "philosophy_en": "Two DMs in front of the defense, an AMC linking play, fast wingers exploiting space on the break. Zero risks, maximum result.",
        "philosophy_it": "Due mediani davanti alla difesa, un trequartista collegamento, ali veloci che sfruttano gli spazi in contropiede. Zero rischi, massimo risultato.",
        "how_to_copy_en": "4-2-3-1 Defensive, blue arrows on the back line and MCs, red arrows on the wingers. Counter ON, long passing on transitions.",
        "how_to_copy_it": "4-2-3-1 Difensivo, frecce blu sulla difesa e i MC, frecce rosse sulle ali. Contropiede ON, passaggi lunghi nelle transizioni."
    },
    {
        "id": "simeone-atletico",
        "manager": "Diego Simeone",
        "team": "Atlético Madrid",
        "era": "2011-oggi",
        "style_en": "Compact 4-4-2, two banks of four, hard tackling",
        "style_it": "4-4-2 compatto, due linee da quattro, contrasti duri",
        "te_formation": "4-4-2 Classic",
        "te_formation_id": "442c",
        "key_attributes_en": ["Tackling", "Marking", "Strength"],
        "key_attributes_it": ["Contrasto", "Marcatura", "Forza"],
        "arrows": "DL↓ DR↓",
        "mentality": "Defensive",
        "philosophy_en": "Two compact banks of four behind a hard-running strike pair. Hard tackling, zero space between the lines, every match a war.",
        "philosophy_it": "Due linee da quattro compatte dietro una coppia d'attacco che corre. Contrasti duri, zero spazio tra le linee, ogni partita una guerra.",
        "how_to_copy_en": "4-4-2 Classic Defensive, hard tackling, man-to-man marking, blue arrows on the full-backs. Don't let your lines drift apart.",
        "how_to_copy_it": "4-4-2 Classico Difensivo, contrasti duri, marcatura a uomo, frecce blu sui terzini. Non lasciar mai distanziare le linee."
    },
    {
        "id": "pep-bayern",
        "manager": "Pep Guardiola",
        "team": "Bayern Munich",
        "era": "2013-2016",
        "style_en": "3-1-5-1 / 3-4-1-2, inverted full-backs, overload central control",
        "style_it": "3-1-5-1 / 3-4-1-2, terzini invertiti, controllo centrale totale",
        "te_formation": "3-1-5-1",
        "te_formation_id": "3151amc",
        "key_attributes_en": ["Passing", "Creativity", "Positioning"],
        "key_attributes_it": ["Passaggio", "Creatività", "Posizionamento"],
        "arrows": "DMC↓ MC↑",
        "mentality": "Attacking",
        "philosophy_en": "Solid back three, holding DM, half-midfielders breaking late, an AMC pulling strings between the lines. Suffocating central density.",
        "philosophy_it": "Difesa a tre solida, mediano davanti, mezzali a inserirsi, un trequartista a tessere tra le linee. Densità centrale soffocante.",
        "how_to_copy_en": "3-1-5-1 Attacking, blue arrow on the DMC, reds on the MCs. Short passing through the middle, possession-oriented.",
        "how_to_copy_it": "3-1-5-1 Attaccante, freccia blu sul DMC, rosse sui MC. Passaggi corti al centro, gioco di possesso."
    },
    {
        "id": "luis-enrique-barca",
        "manager": "Luis Enrique",
        "team": "Barcellona MSN",
        "era": "2014-2017",
        "style_en": "4-3-3 with the MSN trio, attacking trident, vertical possession",
        "style_it": "4-3-3 col tridente MSN, attacco totale, possesso verticale",
        "te_formation": "4-3-3",
        "te_formation_id": "433",
        "key_attributes_en": ["Finishing", "Dribbling", "Creativity"],
        "key_attributes_it": ["Finalizzazione", "Dribbling", "Creatività"],
        "arrows": "AML↑ AMR↑ ST↑",
        "mentality": "Hard Attacking",
        "philosophy_en": "Three world-class forwards: a poacher in the middle, an inverted winger on one flank, a creator on the other. Possession only as a means to feed them.",
        "philosophy_it": "Tre attaccanti di livello mondiale: un finalizzatore al centro, un'ala invertita su un lato, un creatore sull'altro. Il possesso solo per nutrirli.",
        "how_to_copy_en": "4-3-3 Hard Attacking, all front three on red arrows. Maximize Finishing and Dribbling. Short passing, no counter (you ARE the attack).",
        "how_to_copy_it": "4-3-3 Molto Attaccante, tutto il tridente con freccia rossa. Massimizza Finalizzazione e Dribbling. Passaggi corti, niente contropiede (sei tu l'attacco)."
    },
    {
        "id": "ferguson-united",
        "manager": "Alex Ferguson",
        "team": "Manchester United",
        "era": "1999-2013",
        "style_en": "Classic 4-4-2 with width and pace, late goals, never-give-up attitude",
        "style_it": "4-4-2 classico ampio e veloce, gol nel finale, mai mollare",
        "te_formation": "4-4-2 Classic",
        "te_formation_id": "442c",
        "key_attributes_en": ["Crossing", "Heading", "Finishing"],
        "key_attributes_it": ["Cross", "Colpo di testa", "Finalizzazione"],
        "arrows": "ML↑ MR↑",
        "mentality": "Normal",
        "philosophy_en": "British 4-4-2: fast wingers (Giggs/Ronaldo) feed the box, a target man + a poacher, mentality to score in the 90th minute.",
        "philosophy_it": "4-4-2 britannico: ali veloci (Giggs/Ronaldo) servono l'area, un boa + un finalizzatore, mentalità per segnare al 90°.",
        "how_to_copy_en": "4-4-2 Normal, red arrows on the wingers. Down both flanks passing, crossing maxed out. One striker tall (heading), one fast.",
        "how_to_copy_it": "4-4-2 Normale, freccia rossa sulle ali. Passaggi per entrambe le fasce, cross al massimo. Un attaccante alto (testa), uno veloce."
    },
    {
        "id": "tuchel-chelsea",
        "manager": "Thomas Tuchel",
        "team": "Chelsea Champions",
        "era": "2021",
        "style_en": "3-4-2-1, defensive solidity, two creators behind a lone striker",
        "style_it": "3-4-2-1, solidità difensiva, due trequartisti dietro la punta",
        "te_formation": "3-4-1-2",
        "te_formation_id": "3412",
        "key_attributes_en": ["Marking", "Passing", "Creativity"],
        "key_attributes_it": ["Marcatura", "Passaggio", "Creatività"],
        "arrows": "ST↑ ST↑ ML↑ MR↑",
        "mentality": "Normal",
        "philosophy_en": "Three CBs, two wing-backs giving width, two creative attackers (Mount/Havertz) feeding the striker. Solid plus brain.",
        "philosophy_it": "Tre DC, due esterni che danno ampiezza, due trequartisti creativi (Mount/Havertz) che nutrono la punta. Solidità e cervello.",
        "how_to_copy_en": "3-4-1-2 Normal, red arrows on ML/MR and strikers. Train the AMC in Creativity/Passing. Zonal marking.",
        "how_to_copy_it": "3-4-1-2 Normale, freccia rossa su ML/MR e attaccanti. Allena l'AMC in Creatività/Passaggio. Marcatura a zona."
    },
    {
        "id": "ac-milan-modern",
        "manager": "Stefano Pioli / Fonseca",
        "team": "AC Milan",
        "era": "2022-oggi",
        "style_en": "4-2-3-1 with high pressing, two ball-playing DMs, hybrid 4-3-3 in possession",
        "style_it": "4-2-3-1 con pressing alto, doppio mediano costruttore, 4-3-3 ibrido in possesso",
        "te_formation": "4-2-3-1",
        "te_formation_id": "4231",
        "key_attributes_en": ["Passing", "Pace", "Creativity"],
        "key_attributes_it": ["Passaggio", "Velocità", "Creatività"],
        "arrows": "AML↑ AMC↑ AMR↑",
        "mentality": "Attacking",
        "philosophy_en": "Two creative midfielders in front of the defense, an Italian-style #10 (Brahim/Pulisic) plus two flank dribblers (Leao). High pressing and quick passing to keep the rivals in their own half.",
        "philosophy_it": "Due centrocampisti creativi davanti alla difesa, un trequartista all'italiana (Brahim/Pulisic) e due saltatori d'uomo larghi (Leao). Pressing alto e palla che gira veloce per tenere i rivali nella propria metà.",
        "how_to_copy_en": "4-2-3-1 Attacking, high pressing, Down Both Flanks passing, short style. AML/AMR with Pace and Dribbling; AMC with Playmaker ability. Ball-playing DCs.",
        "how_to_copy_it": "4-2-3-1 Offensivo, pressing alto, passaggi sulle fasce, stile corto. AML/AMR con Velocità e Dribbling; AMC con abilità Regista. DC costruttori."
    }
]

# ==================== SEASON STORIES DATA ====================

SEASON_STORIES = [
    {
        "id": "treble-with-433",
        "title_en": "Treble Season with the 4-3-3 False Nine",
        "title_it": "Stagione del Triplete col 4-3-3 Falso Nove",
        "subtitle_en": "How to win League, Cup and Champions in one season",
        "subtitle_it": "Come vincere Campionato, Coppa e Champions in una stagione",
        "formation_used": "4-3-3",
        "outcome_en": "Champions League + League + Cup",
        "outcome_it": "Champions League + Campionato + Coppa",
        "story_en": "Pre-season: build a False Nine striker with high finishing, shooting and creativity (around 95% white attributes at 6 stars). Sign two wingers with the Dual Position ability. In the first 14 league matches use a Normal mentality to gather points without burning fitness, with Down Both Flanks passing. From matchday 15 switch to Attacking with red arrows on the wingers: this is when you create the lead. For the Champions League knockouts switch to Defensive with high pressing only in your own half: the False Nine drops deep, the wingers cut inside in transition. Substitute aggressive players in the last 15 minutes to keep the back line fresh.",
        "story_it": "Pre-stagione: costruisci un attaccante Falso Nove con finalizzazione, tiro e creatività alti (attributi bianchi al 95% circa con 6 stelle). Acquista due ali con abilità Dual Position. Nelle prime 14 partite di campionato usa mentalità Normale per accumulare punti senza bruciare condizione, con passaggi sulle fasce. Dalla giornata 15 passa a Offensiva con frecce rosse sulle ali: è qui che crei il gap. Nei knockout di Champions passa a Difensiva con pressing alto solo nella tua metà: il Falso Nove si abbassa e le ali tagliano dentro in transizione. Sostituisci i giocatori aggressivi negli ultimi 15 minuti per tenere la difesa fresca.",
        "key_lessons_en": [
            "Build the squad in pre-season, not match by match",
            "Switch mentality every 14 days based on objective",
            "Save Fast Trainings for the Champions knockout rounds",
            "Always 80/80 morale and condition before crucial matches"
        ],
        "key_lessons_it": [
            "Costruisci la rosa in pre-season, non partita per partita",
            "Cambia mentalità ogni 14 giorni in base all'obiettivo",
            "Tieni gli Allenamenti Rapidi per i knockout di Champions",
            "Sempre 80/80 di morale e condizione prima delle partite chiave"
        ]
    },
    {
        "id": "underdog-with-451v",
        "title_en": "Underdog Survival with the 4-5-1 V-Style",
        "title_it": "Sopravvivenza da Sfavorito col 4-5-1 V-Style",
        "subtitle_en": "Beat stronger teams without spending tokens",
        "subtitle_it": "Battere squadre più forti senza spendere token",
        "formation_used": "4-5-1 V-Style",
        "outcome_en": "Top-3 finish in a tough league",
        "outcome_it": "Piazzamento in zona Champions in un campionato difficile",
        "story_en": "When you face teams 1-2 stars stronger than you, the 4-5-1 V-Style is the answer. Anchor man DMC, Defensive mentality, Down Both Flanks passing, low pressing, zonal marking and offside trap ON. The AML/AMR with red arrow exploit the space left by their full-backs who push high. The only striker doesn't fight in the box: he drops to receive long balls and lays off to the wingers cutting inside. Each match you concede 60% possession but win 1-0 or 2-1. The secret is keeping all 11 players within 25 meters of each other.",
        "story_it": "Quando affronti squadre 1-2 stelle più forti di te, il 4-5-1 V-Style è la risposta. DMC ancora, mentalità Difensiva, passaggi sulle fasce, pressing basso, marcatura a zona e fuorigioco ON. Gli AML/AMR con freccia rossa sfruttano lo spazio lasciato dai loro terzini che si sbilanciano. L'unico attaccante non combatte in area: si abbassa per ricevere palle lunghe e scarica per le ali che tagliano dentro. Ogni partita concedi il 60% del possesso ma vinci 1-0 o 2-1. Il segreto è tenere tutti gli 11 entro 25 metri uno dall'altro.",
        "key_lessons_en": [
            "Defending well isn't a defect: it's a strategy",
            "The DMC is worth more than a 4th attacker",
            "Trust the offside trap if your line is fast",
            "Don't change shape during the match: trust your plan"
        ],
        "key_lessons_it": [
            "Difendere bene non è un difetto: è una strategia",
            "Il DMC vale più di un quarto attaccante",
            "Fidati del fuorigioco se la tua linea è veloce",
            "Non cambiare modulo durante la partita: fida del piano"
        ]
    },
    {
        "id": "comeback-with-arrows",
        "title_en": "0-2 to 3-2: Comeback with Arrows",
        "title_it": "Dal 0-2 al 3-2: Rimonta con le Frecce",
        "subtitle_en": "How to flip a match in the last 30 minutes",
        "subtitle_it": "Come ribaltare una partita negli ultimi 30 minuti",
        "formation_used": "4-2-3-1 → 3-4-1-2",
        "outcome_en": "Final comeback win 3-2",
        "outcome_it": "Rimonta finale 3-2",
        "story_en": "Down 0-2 at the 60th minute, opponent same star rating. Step 1: pause and save formation. Step 2: switch from 4-2-3-1 to 3-4-1-2 (one CB becomes a striker), Attacking mentality, high pressing, hard tackling, man-to-man marking. Step 3: red arrows on the strikers, ML and MR; blue arrow on the AMC who acts as a deep playmaker. Step 4: bring on the fast striker from the bench in place of a tired MC. Within 15 minutes you usually have 2-3 clear chances. Risk: if you don't score quickly you concede a third, but at 0-2 you don't have much to lose.",
        "story_it": "Sotto 0-2 al 60°, avversario stesso livello stelle. Step 1: metti in pausa e salva la formazione. Step 2: passa dal 4-2-3-1 al 3-4-1-2 (un DC diventa attaccante), mentalità Offensiva, pressing alto, contrasti duri, marcatura a uomo. Step 3: frecce rosse su attaccanti, ML e MR; freccia blu sull'AMC che funge da regista basso. Step 4: inserisci la punta veloce dalla panchina al posto di un MC stanco. In 15 minuti di solito hai 2-3 occasioni nitide. Rischio: se non segni subito ne prendi un terzo, ma al 0-2 non hai molto da perdere.",
        "key_lessons_en": [
            "All-out attack works only when you're losing for sure",
            "Never substitute defenders during a comeback",
            "The 3-4-1-2 is a real comeback weapon",
            "Save useful formations BEFORE the match"
        ],
        "key_lessons_it": [
            "L'attacco totale funziona solo se stai perdendo sicuro",
            "Non sostituire mai i difensori durante una rimonta",
            "Il 3-4-1-2 è una vera arma da rimonta",
            "Salva le formazioni utili PRIMA della partita"
        ]
    },
    {
        "id": "rebuild-with-young",
        "title_en": "Rebuilding the Squad: All-Young Season",
        "title_it": "Ricostruzione Rosa: Stagione tutta Giovani",
        "subtitle_en": "Win with the youth academy without buying anyone",
        "subtitle_it": "Vincere con l'accademia giovanile senza comprare nessuno",
        "formation_used": "4-4-2 Classic",
        "outcome_en": "Mid-table finish, full squad ready for next year",
        "outcome_it": "Salvezza tranquilla, rosa pronta per la stagione dopo",
        "story_en": "Goal: not spend a single token, get 3 six-star youth players, finish the league without relegation. Stick to the 4-4-2 Classic, the simplest formation: less tactical work, more space to manage minutes. Rotate two starting elevens every 3 days. Fast Train daily for the players with the highest growth potential. Friend bonuses at maximum. End of season: a squad with average 5.5 stars but with 3 six-star youth players to bring in next season.",
        "story_it": "Obiettivo: non spendere un token, ottenere 3 giovani da 6 stelle, chiudere il campionato senza retrocedere. Stai sul 4-4-2 Classico, il modulo più semplice: meno lavoro tattico, più spazio per gestire minutaggi. Ruota due undici titolari ogni 3 giorni. Allena con Fast Training tutti i giorni i giocatori col potenziale di crescita più alto. Bonus amici al massimo. A fine stagione: squadra con 5.5 stelle medie ma con 3 giovani da 6 stelle da titolari l'anno dopo.",
        "key_lessons_en": [
            "Sometimes 'mid-table' is the right plan",
            "The youth academy gives more in the long run than the auctions",
            "Rotation prevents injuries and saves morale",
            "Money saved this year is double the value next season"
        ],
        "key_lessons_it": [
            "A volte 'metà classifica' è il piano giusto",
            "L'accademia rende più nel lungo periodo delle aste",
            "La rotazione evita infortuni e salva il morale",
            "I token risparmiati quest'anno valgono il doppio l'anno prossimo"
        ]
    },
    {
        "id": "tiki-taka-fanatic",
        "title_en": "The Tiki-Taka Fanatic: Possession 75%",
        "title_it": "Fanatico del Tiki-Taka: Possesso 75%",
        "subtitle_en": "When numbers lie and you still win",
        "subtitle_it": "Quando i numeri mentono e vinci lo stesso",
        "formation_used": "3-1-5-1 AMC",
        "outcome_en": "League win with 75% average possession but only +12 GD",
        "outcome_it": "Campionato vinto col 75% di possesso medio ma solo +12 di differenza reti",
        "story_en": "3-1-5-1 with the strongest AMC available, anchor DMC, three CBs at 90%+ marking. Possession-obsessed system: Through the Middle passing, short style, no counter, low pressing. You'll see absurd stats: 75% possession, 18-3 shots, only 1-2 goals scored. The opponent will go crazy. Difficult against very deep teams (5-4-1 Flat); easy against everything else. The lesson: if you don't concede chances and have 75% of the ball, sooner or later something happens.",
        "story_it": "3-1-5-1 con il miglior AMC disponibile, DMC ancora, tre DC al 90%+ di marcatura. Sistema ossessionato dal possesso: passaggi al centro, stile corto, no contropiede, pressing basso. Vedrai statistiche assurde: 75% possesso, 18-3 ai tiri, solo 1-2 gol fatti. L'avversario impazzirà. Difficile contro squadre molto chiuse (5-4-1 Flat); facile contro tutto il resto. La lezione: se non concedi occasioni e hai il 75% di palla, prima o poi qualcosa succede.",
        "key_lessons_en": [
            "Possession kills opponent's morale in the long match",
            "An AMC at 95% in his role is worth more than 2 strikers",
            "Against 5-4-1 Flat possession isn't enough: bring crosses",
            "Be patient with the 1-0: don't get nervous"
        ],
        "key_lessons_it": [
            "Il possesso ammazza il morale dell'avversario sulla lunga",
            "Un AMC al 95% nel ruolo vale più di 2 attaccanti",
            "Contro il 5-4-1 Flat il possesso non basta: porta cross",
            "Sii paziente con l'1-0: non innervosirti"
        ]
    },
    {
        "id": "tiki-taka-barca",
        "title_en": "Barça Tiki-Taka in Top Eleven: pure 4-3-3",
        "title_it": "Tiki-Taka del Barça in Top Eleven: il 4-3-3 puro",
        "subtitle_en": "Faithfully recreating Guardiola's 2010/11 Barcelona",
        "subtitle_it": "Ricreare fedelmente il Barcellona di Guardiola 2010/11",
        "formation_used": "4-3-3",
        "outcome_en": "75% possession, 25+ passes per attack, easy league won",
        "outcome_it": "75% di possesso, 25+ passaggi per azione, campionato vinto in scioltezza",
        "story_en": "Inspired by the Barça-2011 4-3-3 Tiki-Taka. Build the squad with the Pep Manchester City profile but reduced to 6 stars: a Ball-Playing DC (the 'Piqué'), a Deep-Lying Playmaker DMC ('Busquets'), two creative MCs ('Xavi/Iniesta' with high Passing and Creativity), a False Nine ST ('Messi'), two AML/AMR with Dribbling and Pace ('Villa/Pedro'). Normal mentality the whole match, Through the Middle passing, Short style, low pressing, no counter (the system never loses the ball). The blue arrow on the DMC is non-negotiable. Result: 75% possession average, opponents collapse in the second half because they've chased all match. Not for fast results: it takes 5-6 matches to click, but once it works it's nearly unstoppable.",
        "story_it": "Ispirata al 4-3-3 Tiki-Taka del Barça-2011. Costruisci la rosa col profilo Pep Manchester City ma ridotta a 6 stelle: un DC Difensore Regista (il 'Piqué'), un DMC Regista Arretrato ('Busquets'), due MC creativi ('Xavi/Iniesta' con Passaggio e Creatività alti), un ST Falso Nove ('Messi'), due AML/AMR con Dribbling e Velocità ('Villa/Pedro'). Mentalità Normale per tutta la partita, passaggi Al Centro, stile Corto, pressing basso, no contropiede (il sistema non perde mai palla). La freccia blu sul DMC è non negoziabile. Risultato: 75% di possesso medio, l'avversario crolla nel secondo tempo perché ha rincorso per tutta la partita. Non per risultati rapidi: servono 5-6 partite perché clicchi, ma quando funziona è quasi inarrestabile.",
        "key_lessons_en": [
            "The DMC playmaker is the system's brain, not the AMC",
            "Don't change mentality during the match: trust the possession",
            "Width with Dribbling > Width with Crossing in pure Tiki-Taka",
            "Against the 5-4-1 Flat: increase to Attacking from minute 65"
        ],
        "key_lessons_it": [
            "Il DMC playmaker è il cervello del sistema, non l'AMC",
            "Non cambiare mentalità durante la partita: fidati del possesso",
            "Ampiezza col Dribbling > ampiezza col Cross nel Tiki-Taka puro",
            "Contro il 5-4-1 Flat: alza a Offensiva dal 65°"
        ]
    }
]

# ==================== FAQ DATA ====================

FAQ = [
    {
        "id": "faq-1",
        "category": "app",
        "question_en": "Where do the data in this app come from?",
        "question_it": "Da dove vengono i dati di questa app?",
        "answer_en": "From a careful study of forums (Top Eleven Forum, Reddit r/topeleven), tactical videos, BlueStacks guides and the BojBojTech reference app, organized in a NotebookLM and structured into 9 datasets.",
        "answer_it": "Da uno studio attento di forum (Top Eleven Forum, Reddit r/topeleven), video tattici, guide BlueStacks e dall'app di riferimento BojBojTech, organizzati in un NotebookLM e strutturati in 9 dataset."
    },
    {
        "id": "faq-2",
        "category": "app",
        "question_en": "Does it work offline?",
        "question_it": "Funziona offline?",
        "answer_en": "Yes, all tactical data is embedded in the app. The AI chat is the only feature that needs internet.",
        "answer_it": "Sì, tutti i dati tattici sono incorporati nell'app. La chat AI è l'unica funzione che richiede internet."
    },
    {
        "id": "faq-3",
        "category": "tactics",
        "question_en": "Why does the same formation give different settings vs stronger/equal/weaker?",
        "question_it": "Perché lo stesso modulo dà impostazioni diverse vs più forte / pari / più debole?",
        "answer_en": "Top Eleven uses an internal star/quality rating: against weaker teams you can push, against stronger ones you must defend deeper. The app calibrates mentality, pressing, marking and arrows accordingly.",
        "answer_it": "Top Eleven usa un rating interno di stelle/qualità: contro squadre più deboli puoi spingere, contro più forti devi difendere più basso. L'app calibra mentalità, pressing, marcatura e frecce di conseguenza."
    },
    {
        "id": "faq-4",
        "category": "tactics",
        "question_en": "Red arrow vs blue arrow: what's the difference?",
        "question_it": "Freccia rossa vs blu: che differenza c'è?",
        "answer_en": "Red = the player advances and joins the attack (offensive). Blue = the player holds a deeper position and defends. Generally: red for fast players, blue for slower ones.",
        "answer_it": "Rossa = il giocatore avanza e partecipa all'attacco (offensiva). Blu = il giocatore mantiene una posizione più arretrata e difende. In linea generale: rossa per i veloci, blu per i lenti."
    },
    {
        "id": "faq-5",
        "category": "tactics",
        "question_en": "When do I use the offside trap?",
        "question_it": "Quando uso il fuorigioco?",
        "answer_en": "ON if the opponent plays long balls to fast strikers and your back line has high positioning. OFF against direct play or compact strikers who don't run in behind.",
        "answer_it": "ON se l'avversario gioca lanci lunghi su attaccanti veloci e la tua linea difensiva ha alto posizionamento. OFF contro avversari diretti o con attaccanti compatti che non scattano alle spalle."
    },
    {
        "id": "faq-6",
        "category": "tactics",
        "question_en": "What's the best formation for everyone?",
        "question_it": "Qual è la migliore formazione in assoluto?",
        "answer_en": "There is no 'best in absolute'. In the 2026 meta the 4-5-1 V-Style is the most versatile and the 4-3-3 with False Nine is the most lethal. Choose based on the players you have, not on the latest trend.",
        "answer_it": "Non esiste 'la migliore in assoluto'. Nel meta 2026 il 4-5-1 V-Style è il più versatile e il 4-3-3 col Falso Nove è il più letale. Scegli in base ai giocatori che hai, non alla moda del momento."
    },
    {
        "id": "faq-7",
        "category": "training",
        "question_en": "How do I get more 6-star players from the youth academy?",
        "question_it": "Come ottengo più giocatori da 6 stelle dall'accademia giovanile?",
        "answer_en": "Spend at least 15 tokens on the academy each season. Choose the highest-quality option available. With consistency it's realistic to get 3 6-star players a year.",
        "answer_it": "Spendi almeno 15 token nell'accademia ogni stagione. Scegli l'opzione di qualità maggiore quando disponibile. Con costanza è realistico ottenere 3 giocatori da 6 stelle l'anno."
    },
    {
        "id": "faq-8",
        "category": "training",
        "question_en": "Should I train all the players or just the starting eleven?",
        "question_it": "Devo allenare tutti i giocatori o solo i titolari?",
        "answer_en": "Priority to the starting eleven. The reserves train only enough to keep morale up. Save Fast Trainings for the key roles (False Nine striker, DMC, AMC).",
        "answer_it": "Priorità ai titolari. Le riserve allenano solo quanto basta per tenere alto il morale. Tieni gli Allenamenti Rapidi per i ruoli chiave (attaccante Falso Nove, DMC, AMC)."
    },
    {
        "id": "faq-9",
        "category": "economy",
        "question_en": "Are tokens worth buying with real money?",
        "question_it": "I token valgono comprarli con soldi veri?",
        "answer_en": "Honest answer: no, if you play casually. Yes if you want to compete at high-association level. With the Special Sponsor and free events you can accumulate enough tokens for an honest mid-table season.",
        "answer_it": "Risposta onesta: no, se giochi a livello casual. Sì se vuoi competere ad alti livelli di associazione. Con lo Special Sponsor e gli eventi gratuiti puoi accumulare token sufficienti per una stagione onesta a metà classifica."
    },
    {
        "id": "faq-10",
        "category": "economy",
        "question_en": "Which sponsor should I choose?",
        "question_it": "Quale sponsor scelgo?",
        "answer_en": "The Special Sponsor (the daily token one) is the most cost-effective in the long run. The shirt sponsor only if you need quick cash for an auction.",
        "answer_it": "Lo Special Sponsor (quello dei token giornalieri) è il più conveniente sul lungo periodo. Lo sponsor maglietta solo se hai bisogno di cassa rapida per un'asta."
    },
    {
        "id": "faq-11",
        "category": "matchday",
        "question_en": "Should I watch the match live or simulate?",
        "question_it": "Devo guardare la partita live o simulare?",
        "answer_en": "Live ONLY if you can make tactical changes (mentality, substitutions). If you can't watch, simulating is the same. Live the matches where you can actually intervene.",
        "answer_it": "Live SOLO se puoi fare cambi tattici (mentalità, sostituzioni). Se non puoi seguire, simulare è la stessa cosa. Vivi solo le partite dove puoi davvero intervenire."
    },
    {
        "id": "faq-12",
        "category": "matchday",
        "question_en": "When should I make the first substitution?",
        "question_it": "Quando faccio la prima sostituzione?",
        "answer_en": "Around the 55-65 minute, prioritizing midfielders who have lost more condition. Save one substitution for an emergency (injury or comeback).",
        "answer_it": "Intorno al 55-65° minuto, dando priorità ai centrocampisti che hanno perso più condizione. Tieni una sostituzione per emergenza (infortunio o rimonta)."
    },
    {
        "id": "faq-13",
        "category": "matchday",
        "question_en": "What does Team Balance mean? Why is it important?",
        "question_it": "Cosa significa Team Balance? Perché è importante?",
        "answer_en": "It's the cohesion index of your team. Below 9.0 you risk losing matches you should win. Keep it between 9.2 and 10. To get it up: rotate sensibly, friend bonuses, avoid 'mutant' players (single overpowered player).",
        "answer_it": "È l'indice di coesione della tua squadra. Sotto 9.0 rischi di perdere partite che dovresti vincere. Tienilo tra 9.2 e 10. Per alzarlo: ruota con criterio, bonus amici, evita giocatori 'mutanti' (un solo overpowered)."
    },
    {
        "id": "faq-14",
        "category": "app",
        "question_en": "Will the data be updated when the meta changes?",
        "question_it": "I dati verranno aggiornati quando cambia il meta?",
        "answer_en": "Yes, the app is built so we can update tactical data when a new meta emerges (currently 2026). The update will arrive with a new app version.",
        "answer_it": "Sì, l'app è costruita per essere aggiornata nei dati tattici quando emerge un nuovo meta (attualmente 2026). L'aggiornamento arriverà con una nuova versione dell'app."
    },
    {
        "id": "faq-15",
        "category": "app",
        "question_en": "Can I suggest a tactic or report an error?",
        "question_it": "Posso suggerire una tattica o segnalare un errore?",
        "answer_en": "Yes — that's the goal. A feedback button will be added in the next versions to gather suggestions and corrections directly from the community.",
        "answer_it": "Sì — è proprio l'obiettivo. Sarà aggiunto un pulsante di feedback nelle prossime versioni per raccogliere suggerimenti e correzioni direttamente dalla community."
    },
    {
        "id": "faq-16",
        "category": "tactics",
        "question_en": "Is it true that 'retro' formations are coming back?",
        "question_it": "È vero che stanno tornando moduli 'retrò'?",
        "answer_en": "Yes, in high-level associations and Discord communities you see modules like the 2-3-2-3 (modern W-M) and 3-3-3-1 used as surprise weapons. They only work with very mobile players with the Dual Position ability.",
        "answer_it": "Sì, nelle associazioni di alto livello e nelle community Discord si vedono moduli come il 2-3-2-3 (W-M moderno) e il 3-3-3-1 usati come armi sorpresa. Funzionano solo con giocatori molto mobili con abilità Dual Position."
    },
    {
        "id": "faq-17",
        "category": "tactics",
        "question_en": "Can I really copy Pep's Tiki-Taka in Top Eleven?",
        "question_it": "Posso davvero copiare il Tiki-Taka di Pep in Top Eleven?",
        "answer_en": "Yes, with the right setup. The key is the deep playmaker at DMC (not at AMC like many think), Normal mentality the whole match, Through the Middle short passing, no counter-attack. Read the 'Barça Tiki-Taka' story in the Stories section for details.",
        "answer_it": "Sì, con il setup giusto. Il segreto è il regista basso a DMC (non a AMC come pensano in tanti), mentalità Normale per tutto il match, passaggi Corti Al Centro, niente contropiede. Leggi la storia 'Tiki-Taka del Barça' nella sezione Storie per i dettagli."
    }
]

# ==================== ARROW TACTICS DATA ====================
# Notation: up arrow = red arrow (forward/attacking), down arrow = blue arrow (back/defensive)

ARROW_TACTICS = [
    {
        "formation_id": "442c",
        "formation": "4-4-2",
        "arrows": "ML↑ MR↑",
        "key_movements_en": "The wide midfielders push up the flanks.",
        "key_movements_it": "Gli esterni di centrocampo spingono sulle fasce.",
        "explanation_en": "Uses wide pace to bypass central defenses and cross.",
        "explanation_it": "Sfrutta la velocità laterale per aggirare le difese centrali e crossare."
    },
    {
        "formation_id": "433",
        "formation": "4-3-3",
        "arrows": "DL↑ DR↑ AML↑ AMR↑",
        "key_movements_en": "Full-backs and wingers push up to create overloads.",
        "key_movements_it": "Terzini e ali salgono per creare superiorità numerica.",
        "explanation_en": "Overloads the opponent's flanks, exploiting weak full-backs.",
        "explanation_it": "Sovraccarica i fianchi dell'avversario sfruttando la debolezza dei difensori laterali."
    },
    {
        "formation_id": "4231",
        "formation": "4-2-3-1",
        "arrows": "AMC↑ AML↑ AMR↑",
        "key_movements_en": "The attacking trio constantly attacks the space.",
        "key_movements_it": "Il trio sulla trequarti attacca costantemente lo spazio.",
        "explanation_en": "Maximizes attacking output when the opponent fields no protective DMC.",
        "explanation_it": "Massimizza la produzione offensiva se l'avversario non schiera un DMC protettivo."
    },
    {
        "formation_id": "451v",
        "formation": "4-5-1 V-Style",
        "arrows": "AML↑ AMR↑ DMC↓",
        "key_movements_en": "The wingers push up while the DMC screens the defense.",
        "key_movements_it": "Le ali spingono, il DMC scherma la difesa.",
        "explanation_en": "A versatile shape that attacks the flanks while keeping central cover against counters.",
        "explanation_it": "Modulo versatile che attacca i fianchi garantendo copertura centrale contro i contropiedi."
    },
    {
        "formation_id": "4222h",
        "formation": "4-2-2-2 Hexagon",
        "arrows": "DMC↓ DMC↓ AML↑ AMR↑",
        "key_movements_en": "Double shield in front of the CBs, wingers pushing forward.",
        "key_movements_it": "Doppia protezione davanti ai DC, ali in proiezione.",
        "explanation_en": "Provides a solid defensive base while enabling lethal breaks down the wings.",
        "explanation_it": "Fornisce una solida base difensiva permettendo ripartenze letali sulle corsie esterne."
    },
    {
        "formation_id": "41212nd",
        "formation": "4-1-2-1-2 ND",
        "arrows": "DL↓ DC↓ DC↓ DR↓ AMC↑ ST↑",
        "key_movements_en": "Back line held, the AMC and strikers pushed forward.",
        "key_movements_it": "Difesa bloccata, trequartista e punte avanzati.",
        "explanation_en": "Protects the center with a deep line while the diamond dominates the final third.",
        "explanation_it": "Protegge il centro con una linea arretrata mentre il rombo domina la trequarti."
    },
    {
        "formation_id": "352f",
        "formation": "3-5-2",
        "arrows": "ML↑ MR↑",
        "key_movements_en": "The wide midfielders cover the whole flank.",
        "key_movements_it": "I centrocampisti laterali coprono tutta la fascia.",
        "explanation_en": "Adds width to the build-up and constant support for the two central strikers.",
        "explanation_it": "Fornisce ampiezza alla manovra e supporto costante alle due punte centrali."
    },
    {
        "formation_id": "541f",
        "formation": "5-4-1",
        "arrows": "ST↑",
        "key_movements_en": "The lone striker chases depth on long balls.",
        "key_movements_it": "L'unica punta cerca la profondità nei lanci lunghi.",
        "explanation_en": "Ideal to park the bus, minimizing defensive risk with a single advanced outlet.",
        "explanation_it": "Ideale per 'parcheggiare l'autobus', minimizzando i rischi difensivi con un solo riferimento avanzato."
    },
    {
        "formation_id": "343",
        "formation": "3-4-3",
        "arrows": "AML↑ AMR↑ ST↑",
        "key_movements_en": "The whole front three stays high.",
        "key_movements_it": "L'intero tridente offensivo rimane alto.",
        "explanation_en": "Applies suffocating pressure on the opponent's three- or four-man defense.",
        "explanation_it": "Esercita una pressione asfissiante sulla difesa a tre o quattro avversaria."
    },
    {
        "formation_id": "3151amc",
        "formation": "3-1-5-1",
        "arrows": "DMC↓ MC↑",
        "key_movements_en": "The holding mid stays deep while the half-midfielders break forward.",
        "key_movements_it": "Il mediano rimane basso, le mezzali si inseriscono.",
        "explanation_en": "Smothers the opponent with a crowded midfield and runners between the lines.",
        "explanation_it": "Soffoca il gioco avversario con un centrocampo folto e inserimenti tra le linee."
    },
    {
        "formation_id": "4141",
        "formation": "4-1-4-1",
        "arrows": "DL↓ DC↓ DC↓ DR↓ DMC↓",
        "key_movements_en": "The entire back line and the holding mid drop deeper.",
        "key_movements_it": "L'intera retroguardia e il mediano si abbassano.",
        "explanation_en": "Compresses defensive space to neutralize strong AMCs and win via counters.",
        "explanation_it": "Soffoca lo spazio difensivo per neutralizzare AMC forti e vincere tramite contropiedi."
    },
    {
        "formation_id": "41311",
        "formation": "4-1-3-1-1",
        "arrows": "DMC↓ MC↓ AMC↓ ST↓",
        "key_movements_en": "The whole central spine sits deeper.",
        "key_movements_it": "Tutta la colonna centrale arretrata.",
        "explanation_en": "Cancels opposing playmakers by removing all space between the defensive and midfield lines.",
        "explanation_it": "Annulla i trequartisti avversari togliendo loro ogni spazio tra le linee di difesa e centrocampo."
    },
    {
        "formation_id": "424",
        "formation": "4-2-4",
        "arrows": "ST↑ ST↑ AML↑ AMR↑",
        "key_movements_en": "All four attackers push forward.",
        "key_movements_it": "I quattro attaccanti spingono in avanti.",
        "explanation_en": "Maximizes attacking pressure to score at the expense of defensive cover.",
        "explanation_it": "Massimizza la pressione offensiva per segnare gol a scapito della copertura difensiva."
    },
    {
        "formation_id": "4321xt",
        "formation": "4-3-2-1 XT (Xmas Tree)",
        "arrows": "DL↑ DR↑",
        "key_movements_en": "The full-backs push up to support the build-up.",
        "key_movements_it": "I terzini salgono per supportare la manovra.",
        "explanation_en": "Adds width to a dense midfield to feed the wingers and the lone striker.",
        "explanation_it": "Fornisce ampiezza a un centrocampo denso per alimentare le ali e l'unica punta."
    },
    {
        "formation_id": "532",
        "formation": "5-3-2",
        "arrows": "ST↑ ST↑",
        "key_movements_en": "The two strikers chase depth.",
        "key_movements_it": "Le due punte cercano la profondità.",
        "explanation_en": "Keeps a solid defensive wall while providing outlets for the counter.",
        "explanation_it": "Permette di mantenere un muro difensivo solido garantendo riferimenti per il contropiede."
    },
    {
        "formation_id": "413n2",
        "formation": "4-1-3N-2",
        "arrows": "MC↑ DMC↓ DL↓ DC↓ DR↓",
        "key_movements_en": "The central MC pushes up while the defense and holding mid stay deep.",
        "key_movements_it": "MC centrale sale, difesa e mediano restano bassi.",
        "explanation_en": "Protects your box and favors central runs to beat formations like the 4-2-3-1.",
        "explanation_it": "Protegge la propria area e favorisce inserimenti centrali per battere moduli come il 4-2-3-1."
    },
    {
        "formation_id": "3412",
        "formation": "3-4-1-2",
        "arrows": "ST↑ ST↑ ML↑ MR↑",
        "key_movements_en": "Strikers and wide midfielders advance.",
        "key_movements_it": "Punte ed esterni di centrocampo avanzano.",
        "explanation_en": "Exploits the wide weakness of opposing defenses through the wide midfielders' runs.",
        "explanation_it": "Sfrutta la debolezza laterale delle difese avversarie tramite la spinta dei centrocampisti laterali."
    },
    {
        "formation_id": "31312",
        "formation": "3-1-3-1-2",
        "arrows": "ST↑ ST↑ MC↑",
        "key_movements_en": "The strikers and a midfielder push forward.",
        "key_movements_it": "Gli attaccanti e il centrocampista avanzano.",
        "explanation_en": "Creates constant shooting chances with an all-out attacking setup.",
        "explanation_it": "Crea costanti opportunità di tiro grazie a un assetto votato totalmente all'attacco."
    },
    {
        "formation_id": "43n3",
        "formation": "4-3N-3",
        "arrows": "ST↑ ST↑ ST↑",
        "key_movements_en": "The front three stays high.",
        "key_movements_it": "Il tridente offensivo rimane alto.",
        "explanation_en": "Applies suffocating pressure on the opposing centre-backs.",
        "explanation_it": "Esercita una pressione asfissiante sui difensori centrali avversari."
    },
    {
        "formation_id": "5212x",
        "formation": "5-2-1-2 X-Style",
        "arrows": "ST↑ ST↑",
        "key_movements_en": "The two strikers push up for the breaks.",
        "key_movements_it": "Le due punte avanzano per le ripartenze.",
        "explanation_en": "Provides maximum defensive protection with outlets ready to strike in transition.",
        "explanation_it": "Garantisce massima protezione difensiva con riferimenti pronti per colpire in transizione."
    },
    {
        "formation_id": "451f",
        "formation": "4-5-1 Flat",
        "arrows": "ML↑ MR↑ DL↑ DR↑",
        "key_movements_en": "Wide midfielders and full-backs push up the flanks.",
        "key_movements_it": "Esterni e terzini spingono sulle fasce.",
        "explanation_en": "Overloads the opponent's flanks to cross constantly into the box.",
        "explanation_it": "Sovraccarica i fianchi avversari per crossare costantemente verso l'area."
    },
    {
        "formation_id": "41212wd",
        "formation": "4-1-2-1-2 WD",
        "arrows": "ST↑ ST↑ ML↑ MR↑ AMC↑",
        "key_movements_en": "Attack, AMC and wingers push forward.",
        "key_movements_it": "Attacco, trequartista e ali in proiezione.",
        "explanation_en": "Uses the width of the diamond to get around centrally-compact defenses.",
        "explanation_it": "Sfrutta l'ampiezza del diamante per aggirare le difese chiuse centralmente."
    },
    {
        "formation_id": "352v",
        "formation": "3-5-2 V",
        "arrows": "ST↑ ST↑ AML↑ AMR↑",
        "key_movements_en": "Strikers and wingers push toward goal.",
        "key_movements_it": "Punte e ali spingono verso la porta.",
        "explanation_en": "Creates instant numerical superiority in both wide and central attacking zones.",
        "explanation_it": "Crea superiorità numerica immediata nelle zone d'attacco esterne e interne."
    },
    {
        "formation_id": "32221b",
        "formation": "3-2-2-2-1 Butterfly",
        "arrows": "ML↑ MR↑ ST↑",
        "key_movements_en": "The wide players and the striker advance.",
        "key_movements_it": "Esterni laterali e punta avanzano.",
        "explanation_en": "Balances the back three by providing continuous support down the flanks.",
        "explanation_it": "Bilancia la difesa a tre fornendo supporto continuo sulle corsie laterali."
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

# ==================== COUNTER QUICK ENDPOINTS ====================

@api_router.get("/counter-quick")
async def get_counter_quick():
    """Quick counter reference: opponent formation -> 3 counter options"""
    return COUNTER_QUICK

@api_router.get("/counter-quick/{category}")
async def get_counter_quick_by_category(category: str):
    """Filter quick counters by category (att, neu, dif)"""
    items = [c for c in COUNTER_QUICK if c["cat"] == category]
    if not items:
        raise HTTPException(status_code=404, detail="No quick counters in this category")
    return items

# ==================== MATCHUP MATRIX ENDPOINTS ====================

@api_router.get("/matchup-matrix")
async def get_matchup_matrix():
    """Get the full matchup matrix: opponent -> 3 counter options (offensive/neutral/defensive)"""
    return MATCHUP_MATRIX

@api_router.get("/matchup-matrix/{opponent}")
async def get_matchup_for_opponent(opponent: str):
    """Get the matchup data for a specific opponent formation"""
    for m in MATCHUP_MATRIX:
        if m["opponent"].lower() == opponent.lower():
            return m
    raise HTTPException(status_code=404, detail="Opponent not found in matchup matrix")

# ==================== CAREER PATHS ENDPOINTS ====================

@api_router.get("/career-paths")
async def get_career_paths():
    """Get all recommended career paths by squad star level"""
    return CAREER_PATHS

@api_router.get("/career-paths/{stars}")
async def get_career_path_for_stars(stars: int):
    """Get the recommended path for a specific star level (3-7+)"""
    for p in CAREER_PATHS:
        if p["stars"] == stars or (stars >= 7 and p["stars"] == 7):
            return p
    raise HTTPException(status_code=404, detail="Career path not found")

# ==================== MY PLAYBOOK ENDPOINTS ====================

@api_router.get("/my-playbook")
async def get_my_playbook():
    """Get the personal tiki-taka playbook: 13 distinct categories"""
    return MY_PLAYBOOK

@api_router.get("/my-playbook/{category_id}")
async def get_my_playbook_category(category_id: str):
    """Get a specific playbook category by id"""
    for c in MY_PLAYBOOK:
        if c["id"] == category_id:
            return c
    raise HTTPException(status_code=404, detail="Playbook category not found")

# ==================== SET PIECE ENDPOINTS ====================

@api_router.get("/set-piece")
async def get_set_piece():
    """Get the full set-piece playbook: 5 categories"""
    return SET_PIECE

@api_router.get("/set-piece/{category_id}")
async def get_set_piece_category(category_id: str):
    """Get a specific set-piece category by id"""
    for c in SET_PIECE:
        if c["id"] == category_id:
            return c
    raise HTTPException(status_code=404, detail="Set-piece category not found")

# ==================== BATTLE CARDS ENDPOINTS ====================

@api_router.get("/battle-cards")
async def get_battle_cards():
    """Get all 10 module-vs-module battle cards"""
    return BATTLE_CARDS

@api_router.get("/battle-cards/{card_id}")
async def get_battle_card(card_id: str):
    """Get a specific battle card by id"""
    for c in BATTLE_CARDS:
        if c["id"] == card_id:
            return c
    raise HTTPException(status_code=404, detail="Battle card not found")

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

# ==================== ABBREVIATIONS ENDPOINTS ====================

@api_router.get("/abbreviations")
async def get_abbreviations():
    """Get the Top Eleven formation abbreviations legend"""
    return ABBREVIATIONS

@api_router.get("/abbreviations/{code}")
async def get_abbreviation_by_code(code: str):
    """Get a specific abbreviation entry by code"""
    code_up = code.upper()
    for a in ABBREVIATIONS:
        if a["code"].upper() == code_up:
            return a
    raise HTTPException(status_code=404, detail="Abbreviation not found")

# ==================== FORMATIONS FILTER BY DEFENSE ====================

@api_router.get("/formations-by-defense/{n}")
async def get_formations_by_defense(n: int):
    """Filter formations by number of defenders (3, 4 or 5)"""
    items = [f for f in FORMATIONS if f.get("defense_count") == n]
    if not items:
        raise HTTPException(status_code=404, detail=f"No formations with defense_count={n}")
    return items

# ==================== SPECIAL ABILITIES ENDPOINTS ====================

@api_router.get("/special-abilities")
async def get_special_abilities():
    """Get all player special abilities"""
    return SPECIAL_ABILITIES

@api_router.get("/special-abilities/{ability_id}")
async def get_special_ability(ability_id: str):
    """Get a specific special ability by id"""
    for ability in SPECIAL_ABILITIES:
        if ability["id"] == ability_id:
            return ability
    raise HTTPException(status_code=404, detail="Special ability not found")

# ==================== TRAINING GUIDE ENDPOINTS ====================

@api_router.get("/training-guide")
async def get_training_guide():
    """Get the full training guide (one entry per position)"""
    return TRAINING_GUIDE

@api_router.get("/training-guide/{position}")
async def get_training_guide_for_position(position: str):
    """Get the training guide for a specific position code (e.g. ST, DC, AMC)"""
    pos = position.upper()
    for entry in TRAINING_GUIDE:
        slots = [p.strip().upper() for p in entry["position"].split("/")]
        if pos in slots:
            return entry
    raise HTTPException(status_code=404, detail="Training guide not found for this position")

# ==================== ARROW TACTICS ENDPOINTS ====================

@api_router.get("/arrow-tactics")
async def get_arrow_tactics():
    """Get recommended tactical arrow setups per formation"""
    return ARROW_TACTICS

@api_router.get("/arrow-tactics/{formation_id}")
async def get_arrow_tactics_for_formation(formation_id: str):
    """Get the recommended arrow setup for a specific formation id"""
    for entry in ARROW_TACTICS:
        if entry["formation_id"] == formation_id:
            return entry
    raise HTTPException(status_code=404, detail="Arrow tactics not found for this formation")

# ==================== REAL TEAMS ENDPOINTS ====================

@api_router.get("/real-teams")
async def get_real_teams():
    """Get the catalogue of famous real-world tactics adapted to Top Eleven"""
    return REAL_TEAMS

@api_router.get("/real-teams/{team_id}")
async def get_real_team(team_id: str):
    """Get a specific real-team tactical card"""
    for team in REAL_TEAMS:
        if team["id"] == team_id:
            return team
    raise HTTPException(status_code=404, detail="Real team not found")

# ==================== SEASON STORIES ENDPOINTS ====================

@api_router.get("/season-stories")
async def get_season_stories():
    """Get all narrated season stories"""
    return SEASON_STORIES

@api_router.get("/season-stories/{story_id}")
async def get_season_story(story_id: str):
    """Get a specific season story"""
    for story in SEASON_STORIES:
        if story["id"] == story_id:
            return story
    raise HTTPException(status_code=404, detail="Season story not found")

# ==================== FAQ ENDPOINTS ====================

@api_router.get("/faq")
async def get_faq():
    """Get all FAQs"""
    return FAQ

@api_router.get("/faq/{category}")
async def get_faq_by_category(category: str):
    """Filter FAQs by category (app, tactics, training, economy, matchday)"""
    items = [f for f in FAQ if f["category"] == category]
    if not items:
        raise HTTPException(status_code=404, detail="No FAQs found for this category")
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
