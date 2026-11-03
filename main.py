from fastapi import FastAPI, Depends, Request, Form, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
import shutil
import datetime
import qrcode
from PIL import Image

SQLALCHEMY_DATABASE_URL = "sqlite:///./medical_pacs.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class PatientRecord(Base):
    __tablename__ = "patient_records"

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String, index=True)
    birth_date = Column(String)
    modality = Column(String)
    image_path = Column(String)
    report = Column(String, default="بانتظار كتابة التقرير الطبي من السكرتارية...")
    qr_code = Column(String)
    created_at = Column(String, default=str(datetime.datetime.now()))

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(SessionMiddleware, secret_key="medical-pacs-super-secret-production-key-2026")

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/qrs", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

env = Environment(loader=FileSystemLoader("templates"))

USERS = {
    "ct_user": {"password": "123", "role": "technician", "modality": "CT", "name": "فني الطبقي المحوري"},
    "mri_user": {"password": "123", "role": "technician", "modality": "MRI", "name": "فني الرنين المغناطيسي"},
    "xray_user": {"password": "123", "role": "technician", "modality": "X-Ray", "name": "فني الأشعة السينية"},
    "echo_user": {"password": "123", "role": "technician", "modality": "Echo", "name": "فني الأمواج فوق الصوتية"},
    "secretary": {"password": "123", "role": "secretary", "name": "موظف الاستقبال والسكرتارية"},
    "samer": {"password": "123", "role": "admin", "name": "الدكتور سامر (الأدمن المطلق)"}
}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- دالة التنظيف التلقائي (حذف البيانات والصور والأكواد الأقدم من 30 يوم) ---
def cleanup_old_records(db: Session):
    try:
        threshold_date = datetime.datetime.now() - datetime.timedelta(days=30)
        records = db.query(PatientRecord).all()
        for record in records:
            if record.created_at:
                try:
                    record_date = datetime.datetime.strptime(record.created_at.split(".")[0], "%Y-%m-%d %H:%M:%S")
                    if record_date < threshold_date:
                        # حذف ملف الصورة الفعلية من القرص
                        if record.image_path:
                            img_file = record.image_path.lstrip("/")
                            if os.path.exists(img_file):
                                os.remove(img_file)
                        # حذف ملف الـ QR الفعلي من القرص
                        if record.qr_code and record.qr_code != "temp.png":
                            qr_file = f"static/qrs/{record.qr_code}"
                            if os.path.exists(qr_file):
                                os.remove(qr_file)
                        # حذف السجل من قاعدة البيانات
                        db.delete(record)
                except Exception:
                    pass
        db.commit()
    except Exception:
        pass

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    if "user" in request.session:
        role = request.session["user"]["role"]
        if role == "technician":
            return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "secretary":
            return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "admin":
            return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
    
    template = env.get_template("login.html")
    return HTMLResponse(content=template.render(request=request))

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    template = env.get_template("login.html")
    return HTMLResponse(content=template.render(request=request))

@app.post("/login")
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username in USERS and USERS[username]["password"] == password:
        request.session["user"] = USERS[username]
        role = USERS[username]["role"]
        if role == "admin":
            return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "secretary":
            return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "technician":
            return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)
    
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/doctor", response_class=HTMLResponse)
def doctor_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # تنفيذ عملية التنظيف التلقائي للسجلات الأقدم من 30 يوماً عند دخول الأدمن
    cleanup_old_records(db)
    
    records = db.query(PatientRecord).all()
    template = env.get_template("doctor.html")
    return HTMLResponse(content=template.render(request=request, records=records, user=request.session["user"]))

@app.post("/doctor/delete/{record_id}")
def doctor_delete_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record:
        if record.image_path:
            img_file = record.image_path.lstrip("/")
            if os.path.exists(img_file):
                os.remove(img_file)
        if record.qr_code and record.qr_code != "temp.png":
            qr_file = f"static/qrs/{record.qr_code}"
            if os.path.exists(qr_file):
                os.remove(qr_file)
        db.delete(record)
        db.commit()
    return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)

# --- مسارات الأرشيف الهرمي (مدعومة كوداً بالكامل لمنع أي TemplateNotFound) ---

@app.get("/doctor/archive", response_class=HTMLResponse)
def archive_home(request: Request):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    html_content = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>أرشيف الفحوصات الطبية الهرمي</title>
    <style>
        body { font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 40px; color: #1e293b; }
        .container { max-width: 900px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; text-align: center; }
        h2 { color: #1e3a8a; margin-bottom: 5px; }
        p { color: #64748b; margin-bottom: 30px; font-size: 14px; }
        .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; margin-bottom: 30px; }
        .card { background: #f1f5f9; border: 1px solid #cbd5e1; padding: 25px; border-radius: 8px; text-decoration: none; color: #1e3a8a; font-weight: bold; font-size: 18px; transition: 0.2s; display: block; }
        .card:hover { background: #1e3a8a; color: white; transform: translateY(-2px); }
        .btn-back { background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }
        .btn-back:hover { background: #475569; }
    </style>
</head>
<body>
    <div class="container">
        <h2>أرشيف الفحوصات الطبية الهرمي</h2>
        <p>اختر نوع الجهاز (Modality) لعرض أرشيف الفحوصات حسب الترتيب الزمني</p>
        <div class="grid">
            <a href="/doctor/archive/CT" class="card">📁 أرشيف الطبقي المحوري (CT)</a>
            <a href="/doctor/archive/MRI" class="card">📁 أرشيف الرنين المغناطيسي (MRI)</a>
            <a href="/doctor/archive/X-Ray" class="card">📁 أرشيف الأشعة السينية (X-Ray)</a>
            <a href="/doctor/archive/Echo" class="card">📁 أرشيف الأمواج فوق الصوتية (Echo)</a>
        </div>
        <a href="/doctor" class="btn-back">← العودة إلى لوحة تحكم الأدمن</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)

@app.get("/doctor/archive/{modality}", response_class=HTMLResponse)
def archive_months(modality: str, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        records = db.query(PatientRecord).all()
        mod_records = [r for r in records if r.modality and r.modality.strip().lower() == modality.strip().lower()]
        months = sorted(list(set([str(r.created_at)[:7] for r in mod_records if r.created_at and len(str(r.created_at)) >= 7])), reverse=True)
        
        months_html = ""
        if months:
            for m in months:
                months_html += f'<a href="/doctor/archive/{modality}/{m}" class="item">📅 شهر: {m}</a>'
        else:
            months_html = '<div class="no-data">لا توجد سجلات مسجلة لهذا الجهاز حتى الآن.</div>'

        html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>أرشيف الشهور - {modality}</title>
    <style>
        body {{ font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 40px; color: #1e293b; }}
        .container {{ max-width: 800px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; text-align: center; }}
        h2 {{ color: #1e3a8a; margin-bottom: 25px; }}
        .list {{ display: flex; flex-direction: column; gap: 12px; margin-bottom: 30px; }}
        .item {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 15px; border-radius: 6px; text-decoration: none; color: #2563eb; font-weight: bold; font-size: 16px; transition: 0.2s; display: block; }}
        .item:hover {{ background: #2563eb; color: white; }}
        .btn-back {{ background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }}
        .no-data {{ color: #64748b; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>أرشيف الشهور لجهاز: {modality}</h2>
        <div class="list">
            {months_html}
        </div>
        <a href="/doctor/archive" class="btn-back">← العودة لاختيار الأجهزة</a>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    except Exception as e:
        return HTMLResponse(content=f"<div style='direction:rtl; font-family:Tahoma; padding:30px; color:red;'><h3>خطأ في الأرشيف (الشهور):</h3><pre>{str(e)}</pre></div>", status_code=500)

@app.get("/doctor/archive/{modality}/{month}", response_class=HTMLResponse)
def archive_days(modality: str, month: str, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        records = db.query(PatientRecord).all()
        mod_records = [r for r in records if r.modality and r.modality.strip().lower() == modality.strip().lower()]
        month_records = [r for r in mod_records if r.created_at and str(r.created_at).startswith(month)]
        days = sorted(list(set([str(r.created_at)[:10] for r in month_records if len(str(r.created_at)) >= 10])), reverse=True)
        
        days_html = ""
        if days:
            for d in days:
                days_html += f'<a href="/doctor/archive/{modality}/{month}/{d}" class="item">📆 يوم: {d}</a>'
        else:
            days_html = '<div class="no-data">لا توجد سجلات في هذا الشهر.</div>'

        html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>أرشيف الأيام - {month}</title>
    <style>
        body {{ font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 40px; color: #1e293b; }}
        .container {{ max-width: 800px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; text-align: center; }}
        h2 {{ color: #1e3a8a; margin-bottom: 25px; }}
        .list {{ display: flex; flex-direction: column; gap: 12px; margin-bottom: 30px; }}
        .item {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 15px; border-radius: 6px; text-decoration: none; color: #16a34a; font-weight: bold; font-size: 16px; transition: 0.2s; display: block; }}
        .item:hover {{ background: #16a34a; color: white; }}
        .btn-back {{ background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }}
        .no-data {{ color: #64748b; padding: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h2>أرشيف الأيام لشهر: {month} ({modality})</h2>
        <div class="list">
            {days_html}
        </div>
        <a href="/doctor/archive/{modality}" class="btn-back">← العودة للشهور</a>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    except Exception as e:
        return HTMLResponse(content=f"<div style='direction:rtl; font-family:Tahoma; padding:30px; color:red;'><h3>خطأ في الأرشيف (الأيام):</h3><pre>{str(e)}</pre></div>", status_code=500)

@app.get("/doctor/archive/{modality}/{month}/{day}", response_class=HTMLResponse)
def archive_records(modality: str, month: str, day: str, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        records = db.query(PatientRecord).all()
        mod_records = [r for r in records if r.modality and r.modality.strip().lower() == modality.strip().lower()]
        day_records = [r for r in mod_records if r.created_at and str(r.created_at).startswith(day)]
        
        rows_html = ""
        if day_records:
            for record in day_records:
                qr_element = f'<img src="/static/qrs/{record.qr_code}" class="qr-img" alt="QR">' if record.qr_code and record.qr_code != "temp.png" else '<span>-</span>'
                rows_html += f"""
                <tr>
                    <td><b>#{record.id}</b></td>
                    <td>{record.patient_name}</td>
                    <td>{record.birth_date}</td>
                    <td><a href="{record.image_path}" target="_self" class="btn">عرض الصورة</a></td>
                    <td>{qr_element}</td>
                    <td>
                        <form action="/save-report" method="post" onsubmit="return confirm('هل أنت متأكد من حفظ وتحديث التقرير الطبي؟');">
                            <input type="hidden" name="record_id" value="{record.id}">
                            <textarea name="report_text">{record.report}</textarea>
                            <br>
                            <button type="submit" class="btn-save" style="margin-top: 5px;">حفظ التقرير</button>
                        </form>
                    </td>
                    <td>
                        <a href="/download-report/{record.id}" class="btn" style="background: #0284c7; margin-bottom: 5px; display: block;">تحميل Word</a>
                        <a href="/patient/{record.id}" target="_blank" class="btn" style="background: #9333ea; display: block;">معاينة الـ QR</a>
                    </td>
                </tr>
                """
        else:
            rows_html = '<tr><td colspan="7" style="padding: 30px; color: #64748b;">لا توجد سجلات في هذا اليوم.</td></tr>'

        html_content = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>سجلات تاريخ: {day}</title>
    <style>
        body {{ font-family: Tahoma, sans-serif; background: #f8fafc; margin: 0; padding: 30px; color: #1e293b; }}
        .container {{ max-width: 1250px; background: white; margin: auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.04); border: 1px solid #e2e8f0; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #1e3a8a; padding-bottom: 15px; margin-bottom: 25px; }}
        .header h2 {{ color: #1e3a8a; margin: 0; font-size: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 25px; }}
        th, td {{ border: 1px solid #e2e8f0; padding: 12px 10px; text-align: center; font-size: 13px; vertical-align: middle; }}
        th {{ background: #1e3a8a; color: white; font-weight: 600; }}
        tr:nth-child(even) {{ background: #f8fafc; }}
        .qr-img {{ width: 50px; height: 50px; object-fit: contain; border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px; background: white; }}
        .btn {{ background: #2563eb; color: white; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-weight: bold; display: inline-block; font-size: 13px; }}
        .btn:hover {{ background: #1d4ed8; }}
        .btn-save {{ background: #16a34a; border: none; cursor: pointer; padding: 6px 14px; color: white; border-radius: 6px; font-weight: bold; font-size: 13px; }}
        .btn-save:hover {{ background: #15803d; }}
        textarea {{ width: 100%; height: 60px; padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-family: Tahoma; font-size: 13px; resize: vertical; }}
        .btn-back {{ background: #64748b; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 14px; display: inline-block; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>سجلات الفحوصات ليوم: {day} ({modality})</h2>
        </div>
        <table>
            <thead>
                <tr>
                    <th>رقم السجل</th>
                    <th>اسم المريض</th>
                    <th>تاريخ الولادة</th>
                    <th>صورة الفحص</th>
                    <th>رمز الـ QR</th>
                    <th>التقرير الطبي التشخيصي</th>
                    <th>الإجراءات</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <a href="/doctor/archive/{modality}/{month}" class="btn-back">← العودة للأشهر</a>
    </div>
</body>
</html>"""
        return HTMLResponse(content=html_content)
    except Exception as e:
        return HTMLResponse(content=f"<div style='direction:rtl; font-family:Tahoma; padding:30px; color:red;'><h3>خطأ في الأرشيف (السجلات):</h3><pre>{str(e)}</pre></div>", status_code=500)

@app.get("/secretary", response_class=HTMLResponse)
def secretary_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "secretary":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    records = db.query(PatientRecord).all()
