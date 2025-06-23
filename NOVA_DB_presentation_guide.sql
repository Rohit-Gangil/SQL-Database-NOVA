
-- ----------------------------------------------
-- DEMO SCRIPT: NOVA DATABASE FUNCTIONALITY WALKTHROUGH
-- For End-Semester Evaluation of CSF212 Project
-- ----------------------------------------------

-- FUNCTIONALITY 1: Add new records (already shown in dummy data)
-- The following procedures were used (and can be shown again):
-- EXECUTE or BEGIN...END for:
--   add_pharmacy, add_company, add_drug, add_doctor, add_patient, add_prescription, add_contract, add_sale

-- Example (Re-run if needed to demonstrate adding):
BEGIN
  add_pharmacy('NovaVizag', 'Vizag', '0891123456');
END;
/
BEGIN
  add_company('Sun Pharma', '1800456789');
END;
/
BEGIN
  add_drug('Ibuprofen', 'Sun Pharma', 'C13H18O2');
END;
/
-- Similarly for patient, doctor, prescription, contract, sale

-- FUNCTIONALITY 2: Get prescription history of a patient in a time range
-- Use procedure: prescription_report(patient_id, from_date, to_date)
BEGIN
  prescription_report('999988887777', TO_DATE('2025-01-01','YYYY-MM-DD'), TO_DATE('2025-12-31','YYYY-MM-DD'));
END;
/

-- FUNCTIONALITY 3: Get details of a prescription for a patient on a specific date
BEGIN
  prescription_details('999988887777', TO_DATE('2025-04-20', 'YYYY-MM-DD'));
END;
/

-- FUNCTIONALITY 4: Get all (10 as required) drugs produced by a pharmaceutical company
BEGIN
  drugs_by_company('Pfizer');
END;
/

-- FUNCTIONALITY 5: Get stock/price details of a pharmacy (which drugs it sells)
BEGIN
  pharmacy_stock('NovaHyd');
END;
/

-- FUNCTIONALITY 6: Get contact details between pharmacy and pharmaceutical company (via contract)
BEGIN
  contact_details('NovaHyd', 'Pfizer');
END;
/

-- FUNCTIONALITY 7: Get all patients under a given doctor
BEGIN
  patients_of_doctor('111122223333');
END;
/

-- Optional: Show deletions (not mandatory for core demo)
-- BEGIN
--   delete_patient('999988887777');
-- END;
-- /

-- DONE!
-- This concludes all functionalities as per project specification.
-- Be ready to explain structure of tables, constraints, and how logic is handled in procedures.

