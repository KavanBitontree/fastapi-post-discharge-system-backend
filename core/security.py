from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from core.config import settings
import hashlib
from fastapi import Request, HTTPException, status

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def hash_token(token: str) -> str:
    """Hashes the refresh token for secure database storage"""
    return hashlib.sha256(token.encode()).hexdigest()

def create_tokens(email: str,pid: int):
    """Generates access and refresh tokens using email as the subject"""

    access_expire = datetime.now(timezone.utc) + timedelta(seconds=30)
    refresh_expire = datetime.now(timezone.utc) + timedelta(days=7)
    
    access_token = jwt.encode(
        {"sub": email,"pid": pid ,"exp": access_expire, "type": "access"}, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    
    refresh_token = jwt.encode(
        {"sub": email, "pid": pid, "exp": refresh_expire, "type": "refresh"}, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    
    return access_token, refresh_token, refresh_expire.timestamp()


def decode_token(token: str):
    """Decodes and validates a JWT token"""
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None
    
    
def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )

    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        email: str = payload.get("sub")
        pid: int = payload.get("pid")
        
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
            
        return {"sub": email, "pid": pid}

    except JWTError:
        raise HTTPException(status_code=401, detail="Token expired or invalid")