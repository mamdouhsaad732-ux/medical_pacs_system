from fastapi import FastAPI, Depends, Request, Form, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
import shutil
import datetime
import qrcode
from PIL import Image

# إعداد قاعدة البيانات وتجنب مشاكل الخيوط المتعددة في SQLite
SQLALCHEMY_DATABASE_URL = "sqlite:///./medical_pacs.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# جدول السجلات الطبية للمرضى
class PatientRecord(Base):
    __tablename__: str = "patient_records"

    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String, index=True)
    birth_date = Column(String)
    modality = Column(String)
    image_path = Column(String)
    report = Column(String, default="بانتظار كتابة التقرير من السكرتارية...")
    qr_code = Column(String)
    created_at = Column(String, default=str(datetime.datetime.now()))

Base.metadata.create_all(bind=engine)

app = FastAPI()

# إضافة وسيط الجلسات (Session Middleware) لإدارة الصلاحيات وتسجيل الدخول والخروج بأمان
app.add_middleware(SessionMiddleware, secret_key="super-secret-key-medical-pacs-system")

# التأكد من إنشاء المجلدات الأساسية تلقائياً
os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/qrs", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

# محرك قوالب Jinja2 مباشر وآمن
env = Environment(loader=FileSystemLoader("templates"))

# قاموس المستخدمين والصلاحيات والأقسام في المركز
USERS = {
    "ct_user": {"password": "123", "role": "technician", "modality": "CT", "name": "فني الطبقي المحوري"},
    "mri_user": {"password": "123", "role": "technician", "modality": "MRI", "name": "فني الرنين المغناطيسي"},
    "xray_user": {"password": "123", "role": "technician", "modality": "X-Ray", "name": "فني الأشعة السينية"},
    "echo_user": {"password": "123", "role": "technician", "modality": "Echo", "name": "فني الإيكو"},
    "secretary": {"password": "123", "role": "secretary", "name": "موظف الاستقبال والسكرتارية"},
    "samer": {"password": "123", "role": "admin", "name": "الدكتور سامر (الأدمن المطلق)"}
}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# مسار الجذر وصفحة تسجيل الدخول
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

# لوحة تحكم الطبيب (الأدمن)
@app.get("/doctor", response_class=HTMLResponse)
def doctor_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    records = db.query(PatientRecord).all()
    template = env.get_template("doctor.html")
    return HTMLResponse(content=template.render(request=request, records=records, user=request.session["user"]))

# لوحة تحكم السكرتارية وكتابة التقارير
@app.get("/secretary", response_class=HTMLResponse)
def secretary_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "secretary":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    records = db.query(PatientRecord).all()
    template = env.get_template("secretary.html")
    return HTMLResponse(content=template.render(request=request, records=records, user=request.session["user"]))

@app.post("/save-report")
def save_report(
    request: Request,
    record_id: int = Form(...),
    report_text: str = Form(...),
    db: Session = Depends(get_db)
):
    if "user" not in request.session or request.session["user"]["role"] != "secretary":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    
    record.report = report_text
    db.commit()
    return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)

# لوحة تحكم الفني (رفع الصور وضغطها بـ PIL وتوليد QR)
@app.get("/technician", response_class=HTMLResponse)
def technician_dashboard(request: Request):
    if "user" not in request.session or request.session["user"]["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    template = env.get_template("technician.html")
    return HTMLResponse(content=template.render(request=request, user=request.session["user"]))

@app.post("/technician/upload")
async def technician_upload(
    request: Request,
    patient_name: str = Form(...),
    birth_date: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if "user" not in request.session or request.session["user"]["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    current_user = request.session["user"]
    modality = current_user.get("modality", "X-Ray")

    temp_path = f"static/uploads/temp_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    clean_filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    final_file_path = f"static/uploads/{clean_filename}"
    
    try:
        img = Image.open(temp_path)
        img.thumbnail((1200, 1200))
        img.save(final_file_path, optimize=True, quality=85)
        os.remove(temp_path)
    except Exception:
        os.rename(temp_path, final_file_path)

    new_record = PatientRecord(
        patient_name=patient_name,
        birth_date=birth_date,
        modality=modality,
        image_path=f"/{final_file_path}",
        qr_code="temp.png"
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    qr_data = f"https://medical-pacs-system.onrender.com/patient/{new_record.id}"
    qr_img = qrcode.make(qr_data)
    
    qr_filename = f"qr_{new_record.id}.png"
    qr_path = f"static/qrs/{qr_filename}"
    qr_img.save(qr_path)
    new_record.qr_code = qr_filename
    db.commit()

    return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)

# صفحة عرض السجل الطبي للمريض (عبر رابط الـ QR)
@app.get("/patient/{record_id}", response_class=HTMLResponse)
def print_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    template = env.get_template("patient.html")
    return HTMLResponse(content=template.render(request=request, record=record))
