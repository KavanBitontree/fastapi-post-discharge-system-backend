from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from core.config import settings
import hashlib
from fastapi import Depends, Request, HTTPException, status
from fastapi.security import APIKeyCookie
from models.refresh_token import RefreshToken
from core.database import get_db

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
cookie_scheme = APIKeyCookie(name="access_token", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def hash_token(token: str) -> str:
    """Hashes the refresh token for secure database storage"""
    return hashlib.sha256(token.encode()).hexdigest()

def create_tokens(email: str, pid: int):
    """Generates access and refresh tokens and links them via rt_hash"""
    access_expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    refresh_expire = datetime.now(timezone.utc) + timedelta(days=7)
    
    refresh_token = jwt.encode(
        {"sub": email, "pid": pid, "exp": refresh_expire, "type": "refresh"}, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    
    rt_hash = hash_token(refresh_token)
    
    access_token = jwt.encode(
        {
            "sub": email, 
            "pid": pid, 
            "rt_hash": rt_hash, 
            "exp": access_expire, 
            "type": "access"
        }, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    
    return access_token, refresh_token, refresh_expire.timestamp()

def create_access_token(email: str, pid: int, rt_hash: str):
    """Generates ONLY an access token tied to an existing refresh token hash"""
    access_expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    access_token = jwt.encode(
        {
            "sub": email, 
            "pid": pid, 
            "rt_hash": rt_hash,
            "exp": access_expire, 
            "type": "access"
        }, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    return access_token

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

from fastapi import Request, Depends, HTTPException, status
from jose import jwt, JWTError
from sqlalchemy.orm import Session
# Ensure your imports match your file structure

def get_current_user(request: Request, token: str = Depends(cookie_scheme), db: Session = Depends(get_db)):
    token = token or request.cookies.get("access_token")
    
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
        rt_hash: str = payload.get("rt_hash")

        if email is None or pid is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        if pid != 0:
            # ONLY CHANGE IS HERE: Query by rt_hash instead of pid
            active_session = db.query(RefreshToken).filter(
                RefreshToken.refresh_token_hashed == rt_hash, 
                RefreshToken.is_revoked == False
            ).first()

            if not active_session:
                raise HTTPException(
                    status_code=401, 
                    # Made sure this matches your interceptor's trigger word exactly
                    detail="Session revoked" 
                )
            
        return {"sub": email, "pid": pid}

    except JWTError:
        raise HTTPException(status_code=401, detail="Token expired or invalid")
    
def require_admin(current_user: dict = Depends(get_current_user)):
    """Security gate that only allows users with PID 0 (Admin)"""
    if current_user.get("pid") != 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Admin privileges required."
        )
    return current_user