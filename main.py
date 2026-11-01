from fastapi import FastAPI, Depends, Request, Form, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
import shutil
import datetime
import qrcode
from PIL import Image

# إعداد قاعدة البيانات
SQLALCHEMY_DATABASE_URL = "sqlite:///./medical_pacs.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# تعريف جدول المرضى
class PatientRecord(Base):
 __tablename__= "patient_records"

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

# التأكد من وجود المجلدات المطلوبة
os.makedirs("static/uploads", exist_ok=True)
os.makedirs("static/qrs", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def login_post(username: str = Form(...), password: str = Form(...)):
    if username == "admin":
        return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
    elif username == "secretary":
        return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)
    elif username == "technician":
        return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/doctor", response_class=HTMLResponse)
def doctor_dashboard(request: Request, db: Session = Depends(get_db)):
    records = db.query(PatientRecord).all()
    return templates.TemplateResponse("doctor.html", {"request": request, "records": records})

@app.get("/secretary", response_class=HTMLResponse)
def secretary_dashboard(request: Request, db: Session = Depends(get_db)):
    records = db.query(PatientRecord).all()
    return templates.TemplateResponse("secretary.html", {"request": request, "records": records})

@app.get("/technician", response_class=HTMLResponse)
def technician_dashboard(request: Request):
    return templates.TemplateResponse("technician.html", {"request": request})

@app.post("/technician/upload")
async def technician_upload(
    patient_name: str = Form(...),
    birth_date: str = Form(...),
    modality: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    file_path = f"static/uploads/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    new_record = PatientRecord(
        patient_name=patient_name,
        birth_date=birth_date,
        modality=modality,
        image_path=f"/{file_path}",
        qr_code="temp.png"
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    # مطابقة مسار الـ QR مع المسار المعرف في التطبيق
    qr_data = f"https://medical-pacs-system.onrender.com/patient/{new_record.id}"
    qr_img = qrcode.make(qr_data)
    qr_filename = f"qr_{new_record.id}.png"
    qr_path = f"static/qrs/{qr_filename}"
    qr_img.save(qr_path)

    new_record.qr_code = qr_filename
    db.commit()

    return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/save-report")
def save_report(
    record_id: int = Form(...),
    report_text: str = Form(...),
    db: Session = Depends(get_db)
):
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    
    record.report = report_text
    db.commit()
    return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)

# المسار الموحد لطباعة وعرض سجل المريض والـ QR
@app.get("/patient/{record_id}", response_class=HTMLResponse)
def print_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    return templates.TemplateResponse("patient.html", {"request": request, "record": record})
