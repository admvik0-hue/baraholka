from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, or_
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import shutil
import os
import uuid
import hashlib
import random
import smtplib
from email.mime.text import MIMEText
from functools import lru_cache
from pathlib import Path
from supabase import create_client, Client

# --- 1. ПОДКЛЮЧЕНИЕ К БД ---
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://admin:secretpass@localhost:5432/baraholka_db")
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 2. МОДЕЛИ ---
class Listing(Base):
    __tablename__ = "listings"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String)
    price = Column(Float)
    owner_type = Column(String, default="INDIVIDUAL")
    is_promoted = Column(Boolean, default=False)
    promotion_expires_at = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    gallery_images = Column(String, nullable=True)
    category = Column(String, nullable=True)
    district = Column(String, nullable=True)
    seller_name = Column(String, nullable=True)
    seller_phone = Column(String, nullable=True)
    owner_email = Column(String, nullable=True)
    is_sold = Column(Boolean, default=False)
    is_blocked = Column(Boolean, default=False)
    views = Column(Integer, default=0)
    created_at = Column(String, nullable=True)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, index=True) # 0 = Техподдержка
    text = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    created_at = Column(String)
    sender_email = Column(String, nullable=True)
    receiver_email = Column(String, nullable=True)
    is_read = Column(Boolean, default=False)

class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, index=True)
    listing_id = Column(Integer, index=True)

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

class District(Base):
    __tablename__ = "districts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    is_verified = Column(Boolean, default=False)
    verification_code = Column(String, nullable=True)
    is_blocked = Column(Boolean, default=False)
    reset_code = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

# --- 3. СХЕМЫ ---
class ListingCreate(BaseModel):
    title: str
    description: str
    price: float
    owner_type: str = "INDIVIDUAL"
    image_url: Optional[str] = None 
    gallery_images: Optional[str] = None
    category: Optional[str] = None
    district: Optional[str] = None
    seller_name: Optional[str] = None
    seller_phone: Optional[str] = None
    owner_email: Optional[str] = None

class ListingResponse(ListingCreate):
    id: int
    is_promoted: bool
    promotion_expires_at: Optional[str] = None
    is_sold: bool = False
    is_blocked: bool = False
    views: int = 0
    created_at: Optional[str] = None
    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    listing_id: int
    text: Optional[str] = None
    image_url: Optional[str] = None
    sender_email: str
    receiver_email: str

class MessageResponse(MessageCreate):
    id: int
    created_at: str
    is_read: bool
    class Config:
        from_attributes = True

class CategoryCreate(BaseModel):
    name: str

class CategoryResponse(CategoryCreate):
    id: int
    class Config:
        from_attributes = True

class DistrictCreate(BaseModel):
    name: str

class DistrictResponse(DistrictCreate):
    id: int
    class Config:
        from_attributes = True

class UserRegister(BaseModel):
    name: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserVerify(BaseModel):
    email: str
    code: str

class ResetRequest(BaseModel):
    email: str

class ResetConfirm(BaseModel):
    email: str
    code: str
    new_password: str

# --- 4. ЗАВИСИМОСТЬ ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 5. ПРИЛОЖЕНИЕ ---
app = FastAPI()
os.makedirs("uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
@lru_cache
def get_supabase() -> Client:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        raise RuntimeError("Не заданы SUPABASE_URL и/или SUPABASE_SERVICE_ROLE_KEY")

    return create_client(supabase_url, supabase_key)

def send_email(to_email: str, subject: str, body: str):
    # Получаем настройки из переменных окружения Render
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 465))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    # Если вы еще не добавили переменные в Render, код просто выведет письмо в консоль
    if not smtp_user or not smtp_password:
        print(f"[EMAIL FALLBACK] Кому: {to_email} | Тема: {subject} | Текст: {body}")
        return

    # Формируем само письмо
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email

    try:
        # Подключаемся к почтовому серверу и отправляем
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f"Письмо успешно отправлено на {to_email}")
    except Exception as e:
        print(f"Ошибка отправки письма: {e}")
        # Если почта не ушла (например, Яндекс заблокировал), код все равно покажется в логах
        print(f"[EMAIL FALLBACK] Кому: {to_email} | Код: {body}")

def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()

@app.get("/")
def read_root():
    return FileResponse("static/index.html")

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

@app.post("/upload/")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Можно загружать только изображения")

    contents = await file.read()

    if not contents:
        raise HTTPException(status_code=400, detail="Файл пустой")

    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Файл больше 10 MB")

    original_name = file.filename or ""
    ext = Path(original_name).suffix.lower()

    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        ext = EXT_BY_MIME.get(file.content_type or "", "")

    if not ext:
        raise HTTPException(status_code=400, detail="Неподдерживаемый формат изображения")

    bucket = os.getenv("SUPABASE_BUCKET", "images")
    object_path = f"uploads/{uuid.uuid4().hex}{ext}"

    try:
        storage = get_supabase().storage.from_(bucket)
        
        storage.upload(
            path=object_path,
            file=contents,
            file_options={
                "content-type": file.content_type or "application/octet-stream",
                "cache-control": "3600",
                "upsert": "false",
            },
        )
        
        public_url = storage.get_public_url(object_path)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка загрузки в Supabase Storage: {e}",
        )

    # Обратите внимание: я добавил image_url, чтобы фронтенд не сломался, 
    # так как старый код возвращал именно image_url.
    return {
        "url": public_url,
        "image_url": public_url,
        "filename": object_path,
    }

# --- АВТОРИЗАЦИЯ И ПОЛЬЗОВАТЕЛИ ---
@app.post("/register")
def register_user(user_data: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    code = str(random.randint(1000, 9999))
    new_user = User(
        name=user_data.name, email=user_data.email,
        password_hash=hash_password(user_data.password),
        is_verified=False, verification_code=code
    )
    db.add(new_user)
    db.commit()

    subject = "Сброс пароля на Районной Барахолке"
    message = f"Здравствуйте!\n\nВаш код для сброса пароля: {code}\n\nЕсли вы не запрашивали сброс пароля, просто проигнорируйте это письмо."
    
    send_email(data.email, subject, message)
    
    return {"status": "ok", "message": "Код для сброса отправлен на вашу почту"}

@app.post("/verify")
def verify_user(data: UserVerify, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user: raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.verification_code != data.code: raise HTTPException(status_code=400, detail="Неверный код подтверждения")
    user.is_verified = True
    user.verification_code = None
    db.commit()
    return {"status": "ok", "message": "Почта успешно подтверждена!"}

@app.post("/login")
def login_user(user_data: UserLogin, db: Session = Depends(get_db)):
    if user_data.email == "admin@admin.com" and user_data.password == "superadmin123":
        return {"status": "ok", "name": "Администратор", "email": user_data.email}
        
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user: raise HTTPException(status_code=400, detail="Неверный email или пароль")
    if not user.is_verified: raise HTTPException(status_code=400, detail="Пожалуйста, подтвердите вашу почту")
    if user.is_blocked: raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован администратором")
    if user.password_hash != hash_password(user_data.password): raise HTTPException(status_code=400, detail="Неверный email или пароль")
        
    return {"status": "ok", "name": user.name, "email": user.email}

@app.post("/reset-password-request")
def request_password_reset(data: ResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user: raise HTTPException(status_code=404, detail="Пользователь не найден")
    code = str(random.randint(1000, 9999))
    user.reset_code = code
    db.commit()
    subject = "Подтверждение регистрации на Районной Барахолке"
    message = f"Здравствуйте!\n\nВаш код для подтверждения регистрации: {code}\n\nЕсли вы не регистрировались на сайте, просто проигнорируйте это письмо."
    
    send_email(user_data.email, subject, message)
    
    return {"status": "ok", "message": "Код отправлен на вашу почту"}

@app.post("/reset-password-confirm")
def confirm_password_reset(data: ResetConfirm, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or user.reset_code != data.code: raise HTTPException(status_code=400, detail="Неверный код или email")
    user.password_hash = hash_password(data.new_password)
    user.reset_code = None
    db.commit()
    return {"status": "ok", "message": "Пароль успешно изменен!"}

# --- ОБЪЯВЛЕНИЯ ---
@app.post("/listings/", response_model=ListingResponse)
def create_listing(listing: ListingCreate, db: Session = Depends(get_db)):
    db_listing = Listing(**listing.dict())
    db_listing.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") 
    db.add(db_listing)
    db.commit()
    db.refresh(db_listing)
    return db_listing

@app.get("/listings/", response_model=List[ListingResponse])
def get_listings(
    skip: int = 0, limit: int = 100, category: Optional[str] = None,
    district: Optional[str] = None, search: Optional[str] = None, sort: Optional[str] = None,
    db: Session = Depends(get_db)
):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expired_promotions = db.query(Listing).filter(Listing.is_promoted == True, Listing.promotion_expires_at < now_str).all()
    if expired_promotions:
        for item in expired_promotions:
            item.is_promoted = False
            item.promotion_expires_at = None
        db.commit()
    
    query = db.query(Listing).filter(Listing.is_sold == False, Listing.is_blocked == False)
    if category: query = query.filter(Listing.category == category)
    if district: query = query.filter(Listing.district == district)
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(Listing.title.ilike(search_term), Listing.description.ilike(search_term)))
    
    if sort == "cheap": query = query.order_by(Listing.is_promoted.desc(), Listing.price.asc())
    elif sort == "expensive": query = query.order_by(Listing.is_promoted.desc(), Listing.price.desc())
    else: query = query.order_by(Listing.is_promoted.desc(), Listing.id.desc())
    
    return query.offset(skip).limit(limit).all()

@app.get("/categories", response_model=List[CategoryResponse])
def get_categories(db: Session = Depends(get_db)):
    if db.query(Category).count() == 0:
        defaults = ["Авто", "Запчасти", "Электроника", "Одежда", "Мебель", "Животные", "Услуги", "Другое"]
        for d in defaults: db.add(Category(name=d))
        db.commit()
    return db.query(Category).all()

@app.post("/categories", response_model=CategoryResponse)
def create_category(cat: CategoryCreate, db: Session = Depends(get_db)):
    if db.query(Category).filter(Category.name == cat.name).first(): raise HTTPException(status_code=400, detail="Такая категория уже существует")
    new_cat = Category(name=cat.name)
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    return new_cat

@app.delete("/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat: raise HTTPException(status_code=404, detail="Категория не найдена")
    db.delete(cat)
    db.commit()
    return {"status": "ok"}

@app.get("/districts", response_model=List[DistrictResponse])
def get_districts(db: Session = Depends(get_db)):
    if db.query(District).count() == 0:
        defaults = ["Центральный", "Северный", "Южный", "Западный", "Восточный", "Пригород"]
        for d in defaults: db.add(District(name=d))
        db.commit()
    return db.query(District).all()

@app.post("/districts", response_model=DistrictResponse)
def create_district(dist: DistrictCreate, db: Session = Depends(get_db)):
    if db.query(District).filter(District.name == dist.name).first(): raise HTTPException(status_code=400, detail="Такой район уже существует")
    new_dist = District(name=dist.name)
    db.add(new_dist)
    db.commit()
    db.refresh(new_dist)
    return new_dist

@app.delete("/districts/{dist_id}")
def delete_district(dist_id: int, db: Session = Depends(get_db)):
    dist = db.query(District).filter(District.id == dist_id).first()
    if not dist: raise HTTPException(status_code=404, detail="Район не найден")
    db.delete(dist)
    db.commit()
    return {"status": "ok"}

@app.get("/my-listings/{email}", response_model=List[ListingResponse])
def get_my_listings(email: str, db: Session = Depends(get_db)):
    return db.query(Listing).filter(Listing.owner_email == email).order_by(Listing.id.desc()).all()

@app.get("/seller-listings/{email}", response_model=List[ListingResponse])
def get_seller_listings(email: str, db: Session = Depends(get_db)):
    return db.query(Listing).filter(Listing.owner_email == email, Listing.is_sold == False, Listing.is_blocked == False).order_by(Listing.is_promoted.desc(), Listing.id.desc()).all()

@app.get("/favorites/{email}")
def get_favorites_ids(email: str, db: Session = Depends(get_db)):
    return [f.listing_id for f in db.query(Favorite).filter(Favorite.user_email == email).all()]

@app.get("/favorites/details/{email}", response_model=List[ListingResponse])
def get_favorites_details(email: str, db: Session = Depends(get_db)):
    fav_ids = [f.listing_id for f in db.query(Favorite).filter(Favorite.user_email == email).all()]
    if not fav_ids: return []
    return db.query(Listing).filter(Listing.id.in_(fav_ids), Listing.is_sold == False, Listing.is_blocked == False).all()

@app.post("/favorites/{email}/{listing_id}")
def add_favorite(email: str, listing_id: int, db: Session = Depends(get_db)):
    if not db.query(Favorite).filter(Favorite.user_email == email, Favorite.listing_id == listing_id).first():
        db.add(Favorite(user_email=email, listing_id=listing_id))
        db.commit()
    return {"status": "ok"}

@app.delete("/favorites/{email}/{listing_id}")
def remove_favorite(email: str, listing_id: int, db: Session = Depends(get_db)):
    db.query(Favorite).filter(Favorite.user_email == email, Favorite.listing_id == listing_id).delete()
    db.commit()
    return {"status": "ok"}

@app.put("/listings/{listing_id}/promote", response_model=ListingResponse)
def promote_listing(listing_id: int, db: Session = Depends(get_db)):
    db_listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not db_listing: raise HTTPException(status_code=404, detail="Объявление не найдено")
    db_listing.is_promoted = True
    db_listing.promotion_expires_at = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    db.refresh(db_listing)
    return db_listing
    
@app.delete("/listings/{listing_id}")
def delete_listing(listing_id: int, db: Session = Depends(get_db)):
    db_listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not db_listing: raise HTTPException(status_code=404, detail="Объявление не найдено")
    db.query(Message).filter(Message.listing_id == listing_id).delete()
    db.query(Favorite).filter(Favorite.listing_id == listing_id).delete()
    db.delete(db_listing)
    db.commit()
    return {"status": "ok", "message": "Объявление удалено"}

@app.put("/listings/{listing_id}", response_model=ListingResponse)
def update_listing(listing_id: int, listing: ListingCreate, db: Session = Depends(get_db)):
    db_listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not db_listing: raise HTTPException(status_code=404, detail="Объявление не найдено")
    for key, value in listing.dict().items(): setattr(db_listing, key, value)
    db.commit()
    db.refresh(db_listing)
    return db_listing

@app.put("/listings/{listing_id}/sold")
def mark_as_sold(listing_id: int, db: Session = Depends(get_db)):
    db_listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not db_listing: raise HTTPException(status_code=404, detail="Объявление не найдено")
    db_listing.is_sold = True
    db_listing.is_promoted = False 
    db.commit()
    return {"status": "ok", "message": "Товар помечен как проданный"}

@app.put("/listings/{listing_id}/view")
def increment_view(listing_id: int, email: Optional[str] = None, db: Session = Depends(get_db)):
    db_listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not db_listing: raise HTTPException(status_code=404, detail="Объявление не найдено")
    if email != db_listing.owner_email:
        db_listing.views = (db_listing.views or 0) + 1
        db.commit()
        db.refresh(db_listing)
    return {"views": db_listing.views}

@app.post("/messages/", response_model=MessageResponse)
def send_message(msg: MessageCreate, db: Session = Depends(get_db)):
    time_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S") 
    db_msg = Message(**msg.dict(), created_at=time_now)
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)
    return db_msg

@app.get("/messages/{listing_id}/{email1}/{email2}", response_model=List[MessageResponse])
def get_messages(listing_id: int, email1: str, email2: str, db: Session = Depends(get_db)):
    return db.query(Message).filter(
        Message.listing_id == listing_id,
        (((Message.sender_email == email1) & (Message.receiver_email == email2)) |
         ((Message.sender_email == email2) & (Message.receiver_email == email1)))
    ).order_by(Message.id.asc()).all()

@app.get("/my-chats/{email}")
def get_my_chats(email: str, db: Session = Depends(get_db)):
    query = db.query(Message).filter(
        (Message.receiver_email == email) | (Message.sender_email == email)
    )
    
    # Если это админ, скрываем техподдержку из общего списка чатов
    if email == "admin@admin.com":
        query = query.filter(Message.listing_id != 0)
        
    messages = query.order_by(Message.id.asc()).all()

    chats = {}
    for msg in messages:
        other_email = msg.sender_email if msg.receiver_email == email else msg.receiver_email
        chat_key = f"{msg.listing_id}_{other_email}"

        if chat_key not in chats:
            listing = db.query(Listing).filter(Listing.id == msg.listing_id).first()
            title = listing.title if listing else ("Техподдержка" if msg.listing_id == 0 else "Товар удален")
            chats[chat_key] = {
                "listing_id": msg.listing_id, 
                "other_email": other_email,
                "title": title, 
                "messages": [], 
                "unread_count": 0
            }
        
        # Вот та самая строка, на которую ругался Python. Теперь отступы ровные!
        chats[chat_key]["messages"].append({
            "text": msg.text, 
            "image_url": msg.image_url, 
            "sender": msg.sender_email, 
            "time": msg.created_at
        })
        
        if msg.receiver_email == email and not msg.is_read: 
            chats[chat_key]["unread_count"] += 1
            
    return chats

@app.get("/unread/{email}")
def get_unread_count(email: str, db: Session = Depends(get_db)):
    count = db.query(Message).filter(Message.receiver_email == email, Message.is_read == False).count()
    return {"count": count}

@app.put("/messages/read/{listing_id}/{sender_email}/{receiver_email}")
def mark_as_read(listing_id: int, sender_email: str, receiver_email: str, db: Session = Depends(get_db)):
    db.query(Message).filter(
        Message.listing_id == listing_id, Message.sender_email == sender_email,
        Message.receiver_email == receiver_email, Message.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"status": "ok"}

# --- АДМИНКА ---
@app.get("/admin/listings", response_model=List[ListingResponse])
def get_all_listings_admin(db: Session = Depends(get_db)):
    return db.query(Listing).order_by(Listing.id.desc()).all()

@app.put("/admin/listings/{listing_id}/toggle-block")
def toggle_block_listing(listing_id: int, db: Session = Depends(get_db)):
    db_listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not db_listing: raise HTTPException(status_code=404, detail="Объявление не найдено")
    db_listing.is_blocked = not db_listing.is_blocked
    db.commit()
    return {"status": "ok", "is_blocked": db_listing.is_blocked}

@app.get("/admin/users")
def get_all_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id.desc()).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "is_verified": u.is_verified, "is_blocked": u.is_blocked} for u in users]

@app.put("/admin/users/{user_id}/toggle-block")
def toggle_user_block(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_blocked = not user.is_blocked
    db.commit()
    return {"status": "ok", "is_blocked": user.is_blocked}

@app.put("/admin/users/{user_id}/force-reset")
def admin_force_reset(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.password_hash = hash_password("123456")
    db.commit()
    return {"status": "ok", "message": "Пароль сброшен на 123456"}

# --- ТЕХПОДДЕРЖКА ДЛЯ АДМИНА ---
@app.get("/admin/support-chats")
def get_support_chats(db: Session = Depends(get_db)):
    messages = db.query(Message).filter(Message.listing_id == 0).order_by(Message.id.asc()).all()
    chats = {}
    for msg in messages:
        other_email = msg.sender_email if msg.sender_email != "admin@admin.com" else msg.receiver_email
        if other_email not in chats:
            chats[other_email] = {"other_email": other_email, "messages": [], "unread_count": 0}
        chats[other_email]["messages"].append({"text": msg.text, "sender": msg.sender_email, "time": msg.created_at})
        if msg.receiver_email == "admin@admin.com" and not msg.is_read:
            chats[other_email]["unread_count"] += 1
    return chats
