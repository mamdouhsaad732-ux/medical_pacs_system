from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from database import Base

class PatientRecord(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    uuid = Column(String, unique=True, index=True, nullable=False)
    patient_name = Column(String, nullable=False)    # اسم المريض الثلاثي
    birth_date = Column(String, nullable=False)      # تاريخ الولادة
    modality = Column(String, nullable=False)        # نوع الجهاز (CT, MRI, X-Ray, Echo)
    image_path = Column(String, nullable=False)       # مسار صورة الفحص الطبي
    report_text = Column(String, nullable=True)     # التقرير التشخيصي (تدخله السكرتاريا بناءً على د. سامر)
    qr_code_path = Column(String, nullable=True)    # رمز التحقق QR
    created_at = Column(DateTime, default=datetime.utcnow)