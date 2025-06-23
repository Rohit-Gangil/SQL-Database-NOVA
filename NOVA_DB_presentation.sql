BEGIN
  add_pharmacy('NovaVizag', 'Vizag', '0891123456');
END;
/

SELECT * FROM PHARMACY;
BEGIN
  add_company('Sun Pharma', '1800456789');
END;
/
BEGIN
  add_drug('Ibuprofen', 'Sun Pharma', 'C13H18O2');
END;
/

-- FUNCTIONALITY 2: Get prescription history of a patient in a time range
BEGIN
  prescription_report('999988887777', TO_DATE('2025-01-01','YYYY-MM-DD'), TO_DATE('2025-12-31','YYYY-MM-DD'));
END;
/

-- FUNCTIONALITY 3: Get details of a prescription for a patient on a specific date
BEGIN
  prescription_details('999988887777', TO_DATE('2025-04-20', 'YYYY-MM-DD'));
END;
/

-- FUNCTIONALITY 4: Get all drugs produced by a pharmaceutical company
BEGIN
  drugs_by_company('Pfizer');
END;
/

-- FUNCTIONALITY 5: Get stock/price details of a pharmacy (which drugs it sells)
BEGIN
  pharmacy_stock('Nova Main');
END;
/

exec

-- FUNCTIONALITY 6: Get contact details between pharmacy and pharmaceutical company (via contract)
BEGIN
  contact_details('NovaHyd', 'Pfizer');
END;
/

-- FUNCTIONALITY 7: Get all patients under a given doctor
BEGIN
  patients_of_doctor('456789012345');
END;
/
exec add_drug('dero','Pfizer','efefe');
select * from drugs;



