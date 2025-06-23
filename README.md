NOVA Pharmacy – Oracle DBMS Project

This project is a comprehensive Oracle SQL & PL/SQL implementation of a pharmacy chain database system. It models the core operations of NOVA Pharmacy across multiple branches, pharmaceutical companies, patients, doctors, and prescriptions, implementing a full-fledged back-end system with robust business logic.

📌 Key Features

- 🧩 **Schema Design**: Normalized relational tables (e.g., Pharmacy, Doctor, Patient, Prescription, Drugs).
- 🧪 **Stored Procedures**: Add/delete entities with business rule validation.
- 📊 **Reports**:
  - Prescription history of a patient by date range
  - Drug inventory per pharmacy
  - Contracts between pharmacies and pharma companies
  - Drugs manufactured by each company
  - Patients associated with each doctor
🔁 **Constraints & Triggers**: Ensures consistency via primary/foreign keys and procedural validation.
🗂️ **Modular Scripts**: Clean separation of schema, data, demo, and guide files.

🗃️ Repository Structure

 NOVA-Pharmacy-DBMS/
├── ER diagram.jpg #ER Diagram for the Database Schema
├── NOVA_DB.sql # Schema definition + stored procedures
├── NOVA_DB_insert_demo.sql # Sample data inserts
├── NOVA_DB_presentation.sql # Live demo query script
├── NOVA_DB_presentation_guide.sql # Commentary and walkthrough guide
├── .gitignore # Prevents temp/log files from being committed
└── README.md # Project overview (this file)


🧰 Technologies Used

- **SQL Dialect**: Oracle SQL / PL-SQL
- **Platform**: Windows 11 with Oracle SQL Developer

🧪 How to Run

1. Launch Oracle SQL Developer or your preferred IDE.
2. Run `NOVA_DB.sql` to create tables and procedures.
3. Execute `NOVA_DB_insert_demo.sql` to populate the database.
4. Use `NOVA_DB_presentation.sql` to showcase system functionality.
5. Refer to `NOVA_DB_presentation_guide.sql` during evaluations for explanations and commands.

💼 Application Domains

- Database Design  
- SQL & PL/SQL Programming  
- Data Integrity & Constraints  
- Business Logic Enforcement  
- Healthcare Information Systems  

📄 License

This repository is intended for academic demonstration purposes only.

---

> Developed by Aadi Deshmukh, Aaditya Bhagat, Rohit Gangil, Vikhyat Singh. 
