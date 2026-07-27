SELECT * FROM PHARMACEUTICAL_COMPANY;
-- Insert Pharmaceutical Companies
BEGIN
  add_company('Pfizer', '1800123456');
END;
/
BEGIN
  add_company('Cipla', '1800654321');
END;
/

-- Insert Pharmacies
BEGIN
  add_pharmacy('NovaHyd', 'Hyderabad', '0401234567');
END;
/
BEGIN
  add_pharmacy('NovaDelhi', 'New Delhi', '0117654321');
END;
/

-- Insert Drugs
BEGIN
  add_drug('Paracetamol', 'Pfizer', 'C8H9NO2');
END;
/
BEGIN
  add_drug('Azithromycin', 'Cipla', 'C38H72N2O12');
END;
/

-- Insert Doctors
BEGIN
  add_doctor('111122223333', 'Dr. Sharma', 'General', 10);
END;
/
BEGIN
  add_doctor('222233334444', 'Dr. Mehta', 'ENT', 15);
END;
/
-- Insert Patients (with their primary doctors)
BEGIN
  add_patient('999988887777', 'Amit Kumar', 'Hyderabad', 30, '111122223333');
END;
/
BEGIN
  add_patient('888877776666', 'Riya Sen', 'Delhi', 24, '222233334444');
END;
/

-- Insert Prescriptions
BEGIN
  add_prescription('111122223333', '999988887777', TO_DATE('2025-04-20', 'YYYY-MM-DD'));
END;
/
BEGIN
  add_prescription('222233334444', '888877776666', TO_DATE('2025-04-21', 'YYYY-MM-DD'));
END;
/

-- Insert Drugs Prescribed
BEGIN
  add_drugs_prescribed('Pfizer', 'Paracetamol', '111122223333', '999988887777', TO_DATE('2025-04-20', 'YYYY-MM-DD'), 2);
END;
/
BEGIN
  add_drugs_prescribed('Cipla', 'Azithromycin', '222233334444', '888877776666', TO_DATE('2025-04-21', 'YYYY-MM-DD'), 1);
END;
/

-- Insert Contracts
BEGIN
  add_contract('Pfizer', 'NovaHyd', TO_DATE('2024-01-01', 'YYYY-MM-DD'), TO_DATE('2026-01-01', 'YYYY-MM-DD'), 'Annual supply', 'Mr. Das');
END;
/
BEGIN
  add_contract('Cipla', 'NovaDelhi', TO_DATE('2024-06-01', 'YYYY-MM-DD'), TO_DATE('2025-12-31', 'YYYY-MM-DD'), 'Trial contract', 'Ms. Roy');
END;
/

-- Insert Pharmacy Sells
BEGIN
  add_sale('NovaHyd', 'Pfizer', 'Paracetamol', 12.5);
END;
/
BEGIN
  add_sale('NovaDelhi', 'Cipla', 'Azithromycin', 25.0);
END;
/

-- Add a new Pharmacy
BEGIN
  add_pharmacy('Nova Central', '900 Central Lane, Pune', '9898989898');
END;
/

-- Delete a Pharmaceutical Company
BEGIN
  delete_company('LifeMeds');
END;
/

-- Get prescriptions of patient '987654321098' between Jan and Dec 2025
BEGIN
  prescription_report('987654321098', DATE '2025-01-01', DATE '2025-12-31');
END;
/

-- Get prescriptions of patient '876543210987' for March-April 2025
BEGIN
  prescription_report('876543210987', DATE '2025-03-01', DATE '2025-04-30');
END;
/
-- Prescription details of patient '987654321098' on 1st April 2025
BEGIN
  prescription_details('987654321098', DATE '2025-04-01');
END;
/

-- Prescription details of patient '654321098765' on 15th April 2025
BEGIN
  prescription_details('654321098765', DATE '2025-04-15');
END;
/
-- List drugs produced by 'PharmaCo'
BEGIN
  drugs_by_company('PharmaCo');
END;
/

-- List drugs produced by 'CurePharma'
BEGIN
  drugs_by_company('CurePharma');
END;
/
-- Get stock at 'Nova Main'
BEGIN
  pharmacy_stock('Nova Main');
END;
/

-- Get stock at 'Nova West'
BEGIN
  pharmacy_stock('Nova West');
END;
/
-- Contract between 'PharmaCo' and 'Nova Main'
BEGIN
  contact_details('Nova Main', 'PharmaCo');
END;
/

-- Contract between 'HealthDrugs' and 'Nova West'
BEGIN
  contact_details('Nova West', 'HealthDrugs');
END;
/
-- List of patients for Dr. Alice Smith (Aadhar: '123456789012')
BEGIN
  patients_of_doctor('123456789012');
END;
/

-- List of patients for Dr. Bob Johnson (Aadhar: '234567890123')
BEGIN
  patients_of_doctor('234567890123');
END;
/
EXEC patients_of_doctor('234567890123');

BEGIN
  prescription_report('876543210987', DATE '2025-03-01', DATE '2025-04-30');
END;
/


