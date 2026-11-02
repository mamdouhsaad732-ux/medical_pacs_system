from fastapi import FastAPI, Depends, Request, Form, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
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
    report = Column(String, default="بانتظار كتابة التقرير من السكرتارية...")
    qr_code = Column(String)
    created_at = Column(String, default=str(datetime.datetime.now()))

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(SessionMiddleware, secret_key="super-secret-key-medical-pacs-system")

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/qrs", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

env = Environment(loader=FileSystemLoader("templates"))

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
    
    records = db.query(PatientRecord).all()
    template = env.get_template("doctor.html")
    return HTMLResponse(content=template.render(request=request, records=records, user=request.session["user"]))

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
    modality: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        # طباعة للتأكد من وصول البيانات وتفاصيل الجلسة
        print("=== محاولة رفع جديدة ===")
        print(f"المريض: {patient_name}, التاريخ: {birth_date}, النوع: {modality}")
        print(f"الملف المرسل: {file.filename}")
        
        if "user" not in request.session:
            print("خطأ: المستخدم غير مسجل في الجلسة!")
            return HTMLResponse(content="<h3 style='color:red;'>خطأ: الجلسة غير مفعلة أو انتهت. يرجى تسجيل الدخول مجدداً.</h3>", status_code=401)

        os.makedirs("static/uploads", exist_ok=True)
        os.makedirs("static/qrs", exist_ok=True)

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
        except Exception as img_err:
            print(f"ملاحظة بخصوص الصورة (تم تخطي المعالجة ونقل الملف مباشرة): {img_err}")
            os.rename(temp_path, final_file_path)

        # إنشاء السجل في قاعدة البيانات
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
        print(f"تم حفظ السجل برقم ID: {new_record.id}")

        # توليد الـ QR
        qr_data = f"https://medical-pacs-system.onrender.com/patient/{new_record.id}"
        qr_img = qrcode.make(qr_data)
        
        qr_filename = f"qr_{new_record.id}.png"
        qr_path = f"static/qrs/{qr_filename}"
        qr_img.save(qr_path)

        new_record.qr_code = qr_filename
        db.commit()
        print("تم توليد وحفظ الـ QR بنجاح!")

        # إرجاع رسالة نجاح واضحة بدلاً من إعادة التوجيه الصامت لنتأكد 100% أن العملية تمت
        return HTMLResponse(content=f"""
            <div style="font-family: Tahoma; text-align: center; margin-top: 50px; direction: rtl;">
                <h2 style="color: green;">تم رفع السجل وتوليد الـ QR بنجاح تام! 🎉</h2>
                <p>رقم السجل: <b>{new_record.id}</b></p>
                <p>اسم المريض: <b>{patient_name}</b></p>
                <br>
                <a href="/technician" style="background: #1e3a8a; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">العودة لصفحة الرفع</a>
                | 
                <a href="/secretary" style="background: #16a34a; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">الانتقال لصفحة السكرتاريا</a>
            </div>
        """)

    except Exception as e:
        import traceback
        err_details = traceback.format_exc()
        print("CRITICAL UPLOAD ERROR:", err_details)
        return HTMLResponse(content=f"<h3 style='color:red;'>حدث خطأ برمجي قاتل أثناء الرفع:</h3><pre>{err_details}</pre>", status_code=500)
@app.get("/patient/{record_id}", response_class=HTMLResponse)
def print_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    template = env.get_template("patient.html")
    return HTMLResponse(content=template.render(request=request, record=record))
