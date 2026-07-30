from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import sqlite3
import secrets
from datetime import datetime
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
import os
from typing import Optional

app = FastAPI(title="HyperLink")

# Секретный ключ для сессий
app.add_middleware(SessionMiddleware, secret_key="hyper-secret-key-change-in-production")

# Монтируем статику
app.mount("/static", StaticFiles(directory="static"), name="static")

# Шаблоны
templates = Jinja2Templates(directory="templates")

# Админ-пароль (в production используйте переменные окружения)
ADMIN_PASSWORD = "admin123"

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
        c.execute("INSERT INTO profile (avatar, name, bio) VALUES (?,?,?)",
                  ("/static/default-avatar.png", "HyperLink", "music producer & artist"))
    
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
    profile = conn.execute("SELECT * FROM profile LIMIT 1").fetchone()
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

# Middleware для проверки админ-сессии
def check_admin(request: Request):
    return request.session.get("admin_auth", False)

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
async def admin_login_page(request: Request):
    if check_admin(request):
        return RedirectResponse("/admin/dashboard")
    return templates.TemplateResponse("admin.html", {"request": request, "error": None})

@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin_auth"] = True
        return RedirectResponse("/admin/dashboard", status_code=303)
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "error": "Неверный пароль"
    })

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not check_admin(request):
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
async def update_profile(request: Request, avatar: str = Form(...), name: str = Form(...), 
                        bio: str = Form(...)):
    if not check_admin(request):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("UPDATE profile SET avatar=?, name=?, bio=? WHERE id=1", 
                (avatar, name, bio))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/update-platform")
async def update_platform(request: Request, platform_id: int = Form(...), 
                         url: str = Form(...)):
    if not check_admin(request):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("UPDATE platforms SET url=? WHERE id=?", (url, platform_id))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/update-release")
async def update_release(request: Request, title: str = Form(...), 
                        release_date: str = Form(...), link: str = Form(...)):
    if not check_admin(request):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("UPDATE releases SET is_active=0 WHERE is_active=1")
    conn.execute("INSERT INTO releases (title, release_date, link, is_active) VALUES (?,?,?,1)",
                (title, release_date, link))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/add-news")
async def add_news(request: Request, text: str = Form(...), date: str = Form(...)):
    if not check_admin(request):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("INSERT INTO news (text, date) VALUES (?,?)", (text, date))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/delete-news")
async def delete_news(request: Request, news_id: int = Form(...)):
    if not check_admin(request):
        raise HTTPException(status_code=403)
    
    conn = get_db()
    conn.execute("DELETE FROM news WHERE id=?", (news_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)