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

@app.post("/doctor/delete/{record_id}")
def doctor_delete_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if record:
        db.delete(record)
        db.commit()
    return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)

# --- مسارات الأرشيف الهرمي (محصنة ضد الأخطاء بنسبة 100%) ---
@app.get("/doctor/archive", response_class=HTMLResponse)
def archive_home(request: Request):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    template = env.get_template("archive_home.html")
    return HTMLResponse(content=template.render(request=request, user=request.session["user"]))

@app.get("/doctor/archive/{modality}", response_class=HTMLResponse)
def archive_months(modality: str, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        records = db.query(PatientRecord).all()
        mod_records = [r for r in records if r.modality and r.modality.strip().lower() == modality.strip().lower()]
        months = sorted(list(set([str(r.created_at)[:7] for r in mod_records if r.created_at and len(str(r.created_at)) >= 7])), reverse=True)
        
        template = env.get_template("archive_months.html")
        return HTMLResponse(content=template.render(request=request, modality=modality, months=months, user=request.session["user"]))
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
        
        template = env.get_template("archive_days.html")
        return HTMLResponse(content=template.render(request=request, modality=modality, month=month, days=days, user=request.session["user"]))
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
        
        template = env.get_template("archive_records.html")
        return HTMLResponse(content=template.render(request=request, modality=modality, month=month, day=day, records=day_records, user=request.session["user"]))
    except Exception as e:
        return HTMLResponse(content=f"<div style='direction:rtl; font-family:Tahoma; padding:30px; color:red;'><h3>خطأ في الأرشيف (السجلات):</h3><pre>{str(e)}</pre></div>", status_code=500)

@app.get("/secretary", response_class=HTMLResponse)
def secretary_dashboard(request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session or request.session["user"]["role"] != "secretary":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    records = db.query(PatientRecord).all()
    template = env.get_template("secretary.html")
    return HTMLResponse(content=template.render(request=request, records=records, user=request.session["user"], success=request.query_params.get("success")))

@app.post("/save-report")
def save_report(
    request: Request,
    record_id: int = Form(...),
    report_text: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user or user["role"] not in ["secretary", "admin"]:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    
    record.report = report_text
    db.commit()
    
    if user["role"] == "admin":
        return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/secretary?success=1", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/download-report/{record_id}")
def download_report(record_id: int, request: Request, db: Session = Depends(get_db)):
    if "user" not in request.session:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    
    file_content = f"""========================================
مركز التشخيص الطبي والتصوير الشعاعي
========================================
رقم السجل: #{record.id}
اسم المريض: {record.patient_name}
تاريخ الولادة: {record.birth_date}
نوع الفحص (Modality): {record.modality}
تاريخ الإنشاء: {record.created_at}
----------------------------------------
التقرير الطبي التشخيصي:
{record.report}
========================================
"""
    return Response(
        content=file_content,
        media_type="application/msword",
        headers={"Content-Disposition": f"attachment; filename=Patient_Report_{record.id}.doc"}
    )

@app.get("/technician", response_class=HTMLResponse)
def technician_dashboard(request: Request):
    if "user" not in request.session or request.session["user"]["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    template = env.get_template("technician.html")
    return HTMLResponse(content=template.render(request=request, user=request.session["user"], success=request.query_params.get("success")))

@app.post("/technician/upload")
async def technician_upload(
    request: Request,
    patient_name: str = Form(...),
    birth_date: str = Form(...),
    modality: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user or user["role"] != "technician":return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        os.makedirs("static/uploads", exist_ok=True)
        os.makedirs("static/qrs", exist_ok=True)

        safe_filename = f"{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename.replace(' ', '_')}"
        final_file_path = f"static/uploads/{safe_filename}"
        
        contents = await file.read()
        with open(final_file_path, "wb") as f:
            f.write(contents)

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

        base_url = str(request.base_url).rstrip("/")
        qr_data = f"{base_url}/patient/{new_record.id}"
        
        qr_img = qrcode.make(qr_data)
        qr_filename = f"qr_{new_record.id}.png"
        qr_path = f"static/qrs/{qr_filename}"
        qr_img.save(qr_path)

        new_record.qr_code = qr_filename
        db.commit()

        return RedirectResponse(url="/technician?success=1", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as e:
        import traceback
        err_details = traceback.format_exc()
        return HTMLResponse(content=f"<h3 style='color:red;'>خطأ أثناء الرفع:</h3><pre>{err_details}</pre>", status_code=500)

@app.get("/patient/{record_id}", response_class=HTMLResponse)
def print_record(record_id: int, request: Request, db: Session = Depends(get_db)):
    record = db.query(PatientRecord).filter(PatientRecord.id == record_id).first()
    if not record:
        return HTMLResponse(content="<div style='font-family:Tahoma; text-align:center; margin-top:50px; direction:rtl;'><h2>عذراً، السجل المطلوب غير موجود أو تم حذفه.</h2></div>", status_code=404)
    template = env.get_template("patient.html")
    return HTMLResponse(content=template.render(request=request, record=record))
