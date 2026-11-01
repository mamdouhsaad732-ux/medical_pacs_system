from fastapi import FastAPI, Request, Depends, Form, File, UploadFile, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session
import os
import uuid
import qrcode
import shutil

import models
from database import engine, get_db

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Medical PACS/RIS System", debug=True)

# تفعيل الجلسة لمدة 30 يوماً كاملة
app.add_middleware(
    SessionMiddleware, 
    secret_key="samer_secure_medical_secret_key", 
    max_age=30 * 24 * 60 * 60
)

os.makedirs("static/uploads", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates_env = Environment(loader=FileSystemLoader("templates"))

# حسابات المستخدمين وصلاحياتهم في المركز
USERS = {
    "ct_user": {"password": "123", "role": "technician", "modality": "CT", "name": "فني الطبقي المحوري"},
    "mri_user": {"password": "123", "role": "technician", "modality": "MRI", "name": "فني الرنين المغناطيسي"},
    "xray_user": {"password": "123", "role": "technician", "modality": "X-Ray", "name": "فني الأشعة السينية"},
    "echo_user": {"password": "123", "role": "technician", "modality": "Echo", "name": "فني الإيكو"},
    "secretary": {"password": "123", "role": "secretary", "name": "موظف الاستقبال والسكرتاريا"},
    "samer": {"password": "123", "role": "admin", "name": "الدكتور سامر (الأدمن المطلق)"}
}

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    if "user" in request.session:
        role = request.session["user"]["role"]
        if role == "technician":
            return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "admin":
            return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
        elif role == "secretary":
            return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    template = templates_env.get_template("login.html")
    return HTMLResponse(content=template.render(request=request, error=None))

@app.post("/login", response_class=HTMLResponse)
def login_action(request: Request, username: str = Form(...), password: str = Form(...)):
    user_data = USERS.get(username)
    if user_data and user_data["password"] == password:
        request.session["user"] = {
            "username": username,
            "role": user_data["role"],
            "name": user_data["name"],
            "modality": user_data.get("modality")
        }
        if user_data["role"] == "technician":
            return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)
        elif user_data["role"] == "admin":
            return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)
        elif user_data["role"] == "secretary":
            return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)
    
    template = templates_env.get_template("login.html")
    return HTMLResponse(content=template.render(request=request, error="اسم المستخدم أو كلمة المرور غير صحيحة"))

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

# --- 1. واجهة الفني (رفع الصورة، الاسم، تاريخ الولادة، وتوليد QR) ---
@app.get("/technician", response_class=HTMLResponse)
def technician_dashboard(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user or user["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    patients = db.query(models.PatientRecord).filter(models.PatientRecord.modality == user["modality"]).all()
    template = templates_env.get_template("technician.html")
    return HTMLResponse(content=template.render(request=request, user=user, patients=patients))

@app.post("/technician/add", response_class=HTMLResponse)
def technician_add(
    request: Request,
    patient_name: str = Form(...),
    birth_date: str = Form(...),
    image_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user or user["role"] != "technician":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    patient_uuid = str(uuid.uuid4())
    modality = user["modality"]
    
    ext = image_file.filename.split(".")[-1] if "." in image_file.filename else "jpg"
    image_filename = f"scan_{patient_uuid}.{ext}"
    image_path = os.path.join("static", "uploads", image_filename)
    
    with open(image_path, "wb") as buffer:
        shutil.copyfileobj(image_file.file, buffer)

    qr_filename = f"qr_{patient_uuid}.png"
    qr_path = os.path.join("static", qr_filename)
    base_url = str(request.base_url).rstrip("/")
    scan_url = f"{base_url}/patient/{patient_uuid}"
    
    img = qrcode.make(scan_url)
    img.save(qr_path)

    new_patient = models.PatientRecord(
        uuid=patient_uuid,
        patient_name=patient_name,
        birth_date=birth_date,
        modality=modality,
        image_path=f"/static/uploads/{image_filename}",
        report_text="بانتظار كتابة التقرير من السكرتارية...",
        qr_code_path=f"/static/{qr_filename}"
    )
    db.add(new_patient)
    db.commit()

    return RedirectResponse(url="/technician", status_code=status.HTTP_303_SEE_OTHER)

# --- 2. واجهة الدكتور سامر (الأدمن المطلق: صلاحيات كاملة قراءة، تعديل، حذف) ---
@app.get("/doctor", response_class=HTMLResponse)
def doctor_dashboard(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    patients = db.query(models.PatientRecord).all()
    template = templates_env.get_template("doctor.html")
    return HTMLResponse(content=template.render(request=request, user=user, patients=patients))

@app.post("/doctor/update/{patient_uuid}", response_class=HTMLResponse)
def admin_update_patient(
    request: Request,
    patient_uuid: str,
    patient_name: str = Form(...),
    birth_date: str = Form(...),
    report_text: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    patient = db.query(models.PatientRecord).filter(models.PatientRecord.uuid == patient_uuid).first()
    if not patient:
        raise HTTPException(status_code=404, detail="المريض غير موجود")
    
    patient.patient_name = patient_name
    patient.birth_date = birth_date
    patient.report_text = report_text
    db.commit()
    return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/doctor/delete/{patient_uuid}", response_class=HTMLResponse)
def admin_delete_patient(
    request: Request,
    patient_uuid: str,
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user or user["role"] != "admin":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    patient = db.query(models.PatientRecord).filter(models.PatientRecord.uuid == patient_uuid).first()
    if patient:
        db.delete(patient)
        db.commit()
    return RedirectResponse(url="/doctor", status_code=status.HTTP_303_SEE_OTHER)

# --- 3. واجهة السكرتاريا (إدخال التقرير بناءً على د. سامر والطباعة) ---
@app.get("/secretary", response_class=HTMLResponse)
def secretary_dashboard(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("user")
    if not user or user["role"] != "secretary":return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    patients = db.query(models.PatientRecord).all()
    template = templates_env.get_template("secretary.html")
    return HTMLResponse(content=template.render(request=request, user=user, patients=patients))

@app.post("/secretary/update/{patient_uuid}", response_class=HTMLResponse)
def secretary_update_report(
    request: Request,
    patient_uuid: str,
    report_text: str = Form(...),
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user or user["role"] != "secretary":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    patient = db.query(models.PatientRecord).filter(models.PatientRecord.uuid == patient_uuid).first()
    if not patient:
        raise HTTPException(status_code=404, detail="المريض غير موجود")
    
    patient.report_text = report_text
    db.commit()
    return RedirectResponse(url="/secretary", status_code=status.HTTP_303_SEE_OTHER)

# --- 4. صفحة المريض النقية عبر مسح الـ QR ---
@app.get("/patient/{patient_uuid}", response_class=HTMLResponse)
def view_patient(request: Request, patient_uuid: str, db: Session = Depends(get_db)):
    patient = db.query(models.PatientRecord).filter(models.PatientRecord.uuid == patient_uuid).first()
    if not patient:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    template = templates_env.get_template("patient.html")
    return HTMLResponse(content=template.render(request=request, patient=patient))