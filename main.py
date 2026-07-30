from fastapi import FastAPI, Request, Form, HTTPException, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import sqlite3
import secrets
from datetime import datetime, timedelta
import uvicorn
import os
from typing import Optional

app = FastAPI(title="HyperLink")

# Монтируем статику
app.mount("/static", StaticFiles(directory="static"), name="static")

# Шаблоны
templates = Jinja2Templates(directory="templates")

# Админ-пароль (в production используйте переменные окружения)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

# Хранилище сессий (в памяти, для production лучше использовать Redis)
admin_sessions = {}

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('hyperlink.db')
    c = conn.cursor()
    
    # Таблица профиля
    c.execute('''CREATE TABLE IF NOT EXISTS profile
                 (id INTEGER PRIMARY KEY, avatar TEXT, name TEXT, bio TEXT)''')
    
    # Таблица платформ
    c.execute('''CREATE TABLE IF NOT EXISTS platforms
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT, url TEXT, icon TEXT, type TEXT)''')
    
    # Таблица релизов
    c.execute('''CREATE TABLE IF NOT EXISTS releases
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  title TEXT, release_date TEXT, link TEXT, is_active BOOLEAN DEFAULT 1)''')
    
    # Таблица новостей
    c.execute('''CREATE TABLE IF NOT EXISTS news
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  text TEXT, date TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Вставляем дефолтные данные если таблицы пустые
    c.execute("SELECT COUNT(*) FROM profile")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO profile (id, avatar, name, bio) VALUES (?,?,?,?)",
                  (1, "/static/default-avatar.png", "HyperLink", "music producer & artist"))
    
    c.execute("SELECT COUNT(*) FROM platforms")
    if c.fetchone()[0] == 0:
        default_platforms = [
            ("Звук", "https://zvuk.com", "fa-solid fa-music", "music"),
            ("Яндекс Музыка", "https://music.yandex.ru", "fa-brands fa-yandex", "music"),
            ("Spotify", "https://open.spotify.com", "fa-brands fa-spotify", "music"),
            ("YouTube", "https://youtube.com", "fa-brands fa-youtube", "social"),
            ("TikTok", "https://tiktok.com", "fa-brands fa-tiktok", "social"),
        ]
        c.executemany("INSERT INTO platforms (name, url, icon, type) VALUES (?,?,?,?)", 
                      default_platforms)
    
    conn.commit()
    conn.close()

init_db()

# Вспомогательные функции для работы с БД
def get_db():
    conn = sqlite3.connect('hyperlink.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_profile():
    conn = get_db()
    profile = conn.execute("SELECT * FROM profile WHERE id=1").fetchone()
    conn.close()
    return profile

def get_platforms(platform_type=None):
    conn = get_db()
    if platform_type:
        platforms = conn.execute("SELECT * FROM platforms WHERE type=? ORDER BY id", 
                                (platform_type,)).fetchall()
    else:
        platforms = conn.execute("SELECT * FROM platforms ORDER BY id").fetchall()
    conn.close()
    return platforms

def get_active_release():
    conn = get_db()
    release = conn.execute("SELECT * FROM releases WHERE is_active=1 ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return release

def get_news(limit=5):
    conn = get_db()
    news = conn.execute("SELECT * FROM news ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return news

# Функция для создания сессии
def create_session():
    session_id = secrets.token_urlsafe(32)
    admin_sessions[session_id] = datetime.now() + timedelta(hours=24)
    return session_id

# Функция проверки сессии
def check_session(session_id: Optional[str] = None):
    if not session_id or session_id not in admin_sessions:
        return False
    
    # Проверяем, не истекла ли сессия
    if admin_sessions[session_id] < datetime.now():
        del admin_sessions[session_id]
        return False
    
    return True

# ============ ПУБЛИЧНЫЕ РОУТЫ ============

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    profile = get_profile()
    social_platforms = get_platforms("social")
    music_platforms = get_platforms("music")
    release = get_active_release()
    news = get_news()
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "profile": profile,
        "socials": social_platforms,
        "music": music_platforms,
        "release": release,
        "news": news
    })

# ============ АДМИН РОУТЫ ============

@app.get("/admin", response_class=HTMLResponse)
async def admin_login_page(request: Request, session_id: Optional[str] = Cookie(None)):
    if check_session(session_id):
        return RedirectResponse("/admin/dashboard")
    return templates.TemplateResponse("admin.html", {"request": request, "error": None})

@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        session_id = create_session()
        response = RedirectResponse("/admin/dashboard", status_code=303)
        response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=86400)
        return response
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "error": "Неверный пароль"
    })

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session_id: Optional[str] = Cookie(None)):
    if not check_session(session_id):
        return RedirectResponse("/admin")
    
    profile = get_profile()
    platforms = get_platforms()
    release = get_active_release()
    news = get_news(limit=10)
    
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "profile": profile,
        "platforms": platforms,
        "release": release,
        "news": news
    })

@app.post("/admin/update-profile")
async def update_profile(request: Request, session_id: Optional[str] = Cookie(None)):
    if not check_session(session_id):
        raise HTTPException(status_code=403)
    
    # Получаем данные из формы
    form_data = await request.form()
    avatar = form_data.get("avatar", "")
    name = form_data.get("name", "")
    bio = form_data.get("bio", "")
    
    print(f"📝 Обновление профиля: name={name}, bio={bio}, avatar={avatar}")
    
    try:
        conn = get_db()
        
        # Проверяем существует ли профиль
        existing = conn.execute("SELECT id FROM profile WHERE id=1").fetchone()
        
        if existing:
            # Обновляем существующий
            conn.execute(
                "UPDATE profile SET avatar=?, name=?, bio=? WHERE id=1",
                (avatar, name, bio)
            )
            print("✅ Профиль обновлен")
        else:
            # Создаем новый
            conn.execute(
                "INSERT INTO profile (id, avatar, name, bio) VALUES (1, ?, ?, ?)",
                (avatar, name, bio)
            )
            print("✅ Профиль создан заново")
        
        conn.commit()
        conn.close()
        
        # Перенаправляем с сообщением об успехе
        response = RedirectResponse("/admin/dashboard?success=profile_updated", status_code=303)
        return response
        
    except Exception as e:
        print(f"❌ Ошибка при сохранении профиля: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {str(e)}")

@app.post("/admin/update-platform")
async def update_platform(request: Request, platform_id: int = Form(...), 
                         url: str = Form(...), session_id: Optional[str] = Cookie(None)):
    if not check_session(session_id):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("UPDATE platforms SET url=? WHERE id=?", (url, platform_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard?success=platform_updated", status_code=303)

@app.post("/admin/update-release")
async def update_release(request: Request, title: str = Form(...), 
                        release_date: str = Form(...), link: str = Form(...),
                        session_id: Optional[str] = Cookie(None)):
    if not check_session(session_id):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    # Деактивируем все предыдущие релизы
    conn.execute("UPDATE releases SET is_active=0 WHERE is_active=1")
    # Добавляем новый
    conn.execute("INSERT INTO releases (title, release_date, link, is_active) VALUES (?,?,?,1)",
                (title, release_date, link))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard?success=release_updated", status_code=303)

@app.post("/admin/add-news")
async def add_news(request: Request, text: str = Form(...), date: str = Form(...),
                  session_id: Optional[str] = Cookie(None)):
    if not check_session(session_id):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("INSERT INTO news (text, date) VALUES (?,?)", (text, date))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard?success=news_added", status_code=303)

@app.post("/admin/delete-news")
async def delete_news(request: Request, news_id: int = Form(...),
                     session_id: Optional[str] = Cookie(None)):
    if not check_session(session_id):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("DELETE FROM news WHERE id=?", (news_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard?success=news_deleted", status_code=303)

@app.get("/admin/logout")
async def admin_logout(session_id: Optional[str] = Cookie(None)):
    if session_id in admin_sessions:
        del admin_sessions[session_id]
    
    response = RedirectResponse("/admin")
    response.delete_cookie("session_id")
    return response

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)