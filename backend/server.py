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

# ==================== FORMATIONS DATA ====================

FORMATIONS = [
    {
        "id": "442",
        "name": "4-4-2",
        "description_en": "Classic balanced formation. Strong in both defense and attack with 4 defenders, 4 midfielders, and 2 strikers.",
        "description_it": "Formazione classica ed equilibrata. Forte sia in difesa che in attacco con 4 difensori, 4 centrocampisti e 2 attaccanti.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST", "ST"],
        "strengths_en": ["Balanced", "Good width", "Partnership up front"],
        "strengths_it": ["Equilibrata", "Buona ampiezza", "Partnership in attacco"],
        "weaknesses_en": ["Can be outnumbered in midfield", "Requires fit wingers"],
        "weaknesses_it": ["Può essere superata numericamente a centrocampo", "Richiede ali in forma"]
    },
    {
        "id": "433",
        "name": "4-3-3",
        "description_en": "Attacking formation with 3 forwards. Great for possession and pressing high up the pitch.",
        "description_it": "Formazione offensiva con 3 attaccanti. Ottima per il possesso palla e il pressing alto.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MC", "MC", "MC", "RW", "ST", "LW"],
        "strengths_en": ["High pressing", "Width in attack", "Creative midfield"],
        "strengths_it": ["Pressing alto", "Ampiezza in attacco", "Centrocampo creativo"],
        "weaknesses_en": ["Vulnerable to counters", "Midfield can be overrun"],
        "weaknesses_it": ["Vulnerabile ai contropiedi", "Centrocampo può essere sopraffatto"]
    },
    {
        "id": "352",
        "name": "3-5-2",
        "description_en": "Midfield-dominant formation with wing-backs. Controls the center of the pitch.",
        "description_it": "Formazione dominante a centrocampo con esterni. Controlla il centro del campo.",
        "positions": ["GK", "DC", "DC", "DC", "DMC", "MC", "MC", "MC", "AMC", "ST", "ST"],
        "strengths_en": ["Midfield control", "Numerical advantage in center", "Partnership up front"],
        "strengths_it": ["Controllo del centrocampo", "Vantaggio numerico al centro", "Partnership in attacco"],
        "weaknesses_en": ["Exposed flanks", "Requires versatile wing-backs"],
        "weaknesses_it": ["Fianchi esposti", "Richiede esterni versatili"]
    },
    {
        "id": "4231",
        "name": "4-2-3-1",
        "description_en": "Modern defensive formation with attacking midfielder. Great balance between defense and attack.",
        "description_it": "Formazione moderna difensiva con trequartista. Grande equilibrio tra difesa e attacco.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "DMC", "MR", "AMC", "ML", "ST"],
        "strengths_en": ["Defensive stability", "Creative playmaker", "Compact midfield"],
        "strengths_it": ["Stabilità difensiva", "Regista creativo", "Centrocampo compatto"],
        "weaknesses_en": ["Lone striker isolated", "Depends heavily on #10"],
        "weaknesses_it": ["Attaccante solitario isolato", "Dipende molto dal trequartista"]
    },
    {
        "id": "451",
        "name": "4-5-1",
        "description_en": "Ultra-defensive formation. Great for absorbing pressure and counter-attacking.",
        "description_it": "Formazione ultra-difensiva. Ottima per assorbire la pressione e ripartire in contropiede.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "MR", "MC", "MC", "MC", "ML", "ST"],
        "strengths_en": ["Defensive solidity", "Midfield dominance", "Counter-attack potential"],
        "strengths_it": ["Solidità difensiva", "Dominio a centrocampo", "Potenziale di contropiede"],
        "weaknesses_en": ["Lone striker", "Limited attacking options"],
        "weaknesses_it": ["Attaccante solitario", "Opzioni offensive limitate"]
    },
    {
        "id": "343",
        "name": "3-4-3",
        "description_en": "Ultra-attacking formation. High risk, high reward with 3 defenders and 3 forwards.",
        "description_it": "Formazione ultra-offensiva. Alto rischio, alta ricompensa con 3 difensori e 3 attaccanti.",
        "positions": ["GK", "DC", "DC", "DC", "MR", "MC", "MC", "ML", "RW", "ST", "LW"],
        "strengths_en": ["Attacking firepower", "Width", "Pressing intensity"],
        "strengths_it": ["Potenza offensiva", "Ampiezza", "Intensità del pressing"],
        "weaknesses_en": ["Defensively weak", "Exposed to counters"],
        "weaknesses_it": ["Difensivamente debole", "Esposta ai contropiedi"]
    },
    {
        "id": "541",
        "name": "5-4-1",
        "description_en": "Parking the bus formation. Maximum defensive solidity with 5 at the back.",
        "description_it": "Formazione catenaccio. Massima solidità difensiva con 5 in difesa.",
        "positions": ["GK", "DR", "DC", "DC", "DC", "DL", "MR", "MC", "MC", "ML", "ST"],
        "strengths_en": ["Maximum defense", "Hard to break down", "Ideal for protecting leads"],
        "strengths_it": ["Massima difesa", "Difficile da penetrare", "Ideale per proteggere vantaggi"],
        "weaknesses_en": ["Very limited attack", "Requires discipline"],
        "weaknesses_it": ["Attacco molto limitato", "Richiede disciplina"]
    },
    {
        "id": "4141",
        "name": "4-1-4-1",
        "description_en": "Defensive midfield anchor formation. Single pivot protects the back four.",
        "description_it": "Formazione con ancoraggio difensivo a centrocampo. Singolo pivot protegge la difesa.",
        "positions": ["GK", "DR", "DC", "DC", "DL", "DMC", "MR", "MC", "MC", "ML", "ST"],
        "strengths_en": ["Defensive shield", "Wide midfield", "Balanced structure"],
        "strengths_it": ["Scudo difensivo", "Centrocampo ampio", "Struttura equilibrata"],
        "weaknesses_en": ["Lone striker", "Pivot can be overloaded"],
        "weaknesses_it": ["Attaccante solitario", "Pivot può essere sovraccaricato"]
    }
]

COUNTER_TACTICS = [
    {"formation": "442", "counters": ["433", "4231"], "reason_en": "4-3-3 and 4-2-3-1 overload the midfield against 4-4-2", "reason_it": "4-3-3 e 4-2-3-1 sovraccaricano il centrocampo contro il 4-4-2"},
    {"formation": "433", "counters": ["451", "4141"], "reason_en": "Compact midfield formations neutralize 4-3-3's width", "reason_it": "Formazioni compatte a centrocampo neutralizzano l'ampiezza del 4-3-3"},
    {"formation": "352", "counters": ["433", "343"], "reason_en": "Wide formations exploit 3-5-2's exposed flanks", "reason_it": "Formazioni ampie sfruttano i fianchi esposti del 3-5-2"},
    {"formation": "4231", "counters": ["352", "433"], "reason_en": "Midfield-heavy formations can overrun the double pivot", "reason_it": "Formazioni pesanti a centrocampo possono sopraffare il doppio pivot"},
    {"formation": "451", "counters": ["352", "343"], "reason_en": "Attacking formations can break down 4-5-1 with numbers", "reason_it": "Formazioni offensive possono sfondare il 4-5-1 con i numeri"},
    {"formation": "343", "counters": ["541", "451"], "reason_en": "Defensive formations exploit 3-4-3's weak defense", "reason_it": "Formazioni difensive sfruttano la difesa debole del 3-4-3"},
    {"formation": "541", "counters": ["433", "343"], "reason_en": "Attacking width stretches 5-4-1's defensive line", "reason_it": "L'ampiezza offensiva distende la linea difensiva del 5-4-1"},
    {"formation": "4141", "counters": ["4231", "352"], "reason_en": "Creative formations can bypass the single pivot", "reason_it": "Formazioni creative possono aggirare il singolo pivot"}
]

SCOUT_TIPS = [
    {
        "id": "1",
        "category": "defense",
        "title_en": "Center Back Selection",
        "title_it": "Selezione Difensori Centrali",
        "content_en": "Look for CBs with high Tackling, Heading, and Positioning. Speed is important to recover against fast strikers. Prioritize players with 4+ stars.",
        "content_it": "Cerca DC con alto Contrasto, Colpo di Testa e Posizionamento. La velocità è importante per recuperare contro attaccanti veloci. Dai priorità a giocatori con 4+ stelle."
    },
    {
        "id": "2",
        "category": "midfield",
        "title_en": "Midfield Balance",
        "title_it": "Equilibrio a Centrocampo",
        "content_en": "Have a mix of defensive (DMC) and attacking (AMC) midfielders. ML/MR should have good Crossing and Pace. Central midfielders need Passing and Stamina.",
        "content_it": "Avere un mix di centrocampisti difensivi (CDC) e offensivi (CAC). ML/MR devono avere buon Cross e Velocità. I centrocampisti centrali necessitano Passaggio e Resistenza."
    },
    {
        "id": "3",
        "category": "attack",
        "title_en": "Striker Types",
        "title_it": "Tipi di Attaccante",
        "content_en": "Choose strikers based on your tactics. Target men need Heading and Strength. Speedsters need Pace and Finishing. Complete forwards are rare but valuable.",
        "content_it": "Scegli gli attaccanti in base alle tue tattiche. I pivot necessitano Colpo di Testa e Forza. I velocisti necessitano Velocità e Finalizzazione. Gli attaccanti completi sono rari ma preziosi."
    },
    {
        "id": "4",
        "category": "training",
        "title_en": "Training Priority",
        "title_it": "Priorità Allenamento",
        "content_en": "Focus training on your starting 11 first. Use Quick Training early in seasons. Save intensive drills for important matches. Maintain 80/80 teamplay before big games.",
        "content_it": "Concentra l'allenamento prima sui titolari. Usa Allenamento Rapido all'inizio delle stagioni. Conserva gli esercizi intensivi per partite importanti. Mantieni 80/80 di affiatamento prima di grandi partite."
    },
    {
        "id": "5",
        "category": "budget",
        "title_en": "Budget Management",
        "title_it": "Gestione Budget",
        "content_en": "Don't spend all money on transfers. Keep reserves for player salaries and training. Scout list players cost more but can be signed immediately.",
        "content_it": "Non spendere tutti i soldi in trasferimenti. Tieni riserve per stipendi e allenamento. I giocatori dalla lista scout costano di più ma possono essere ingaggiati subito."
    },
    {
        "id": "6",
        "category": "tactics",
        "title_en": "In-Match Adjustments",
        "title_it": "Aggiustamenti in Partita",
        "content_en": "Change to defensive when leading. Switch to attacking when trailing. Use counters against possession-based opponents. Low pressing saves stamina for 2 daily games.",
        "content_it": "Passa a difensivo quando sei in vantaggio. Passa a offensivo quando sei in svantaggio. Usa contropiedi contro avversari che giocano sul possesso. Pressing basso risparmia energia per 2 partite giornaliere."
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
