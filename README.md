# Rental Management System (ระบบเช่าบ้าน)

A local rental / property management web application built for a university project. Customers request and manage rentals; staff manage properties, contracts, billing, repairs and move-outs. It runs on one computer with Flask + SQLite, with no internet connection and no cloud hosting.

---

## 1. Project Overview

Manages the full rental lifecycle: rental request → contract → invoice → payment → repairs / extensions → move-out and deposit settlement, while keeping historical records.

**Customer:** submit rental requests; view contracts, invoices and balances; submit payment evidence; submit repair requests (with photos); submit extension/renovation requests (with documents); submit move-out notices.

**Staff:** manage properties and units; manage customers; handle rental requests and create contracts; issue invoices and verify payments; manage repairs; review extension requests; process move-outs, damage deductions and deposit settlement; view tenant history; log incidents.

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 (developed and tested with 3.13.16) |
| Web framework | Flask 3.1 (also installs Werkzeug and Jinja2) |
| Database | SQLite (Python standard library `sqlite3`) |
| Frontend | HTML, CSS (no JavaScript framework; pages are server-rendered) |
| Packaging | PyInstaller |
| Testing | Python `unittest` (standard library) |

`requirements.txt` contains only `Flask>=3.0`. PyInstaller is a build-time tool, installed separately.

## 3. System Architecture

```
Browser (Chrome / Edge)
   ↓
Flask Web Application (app/views)
   ↓
Business Logic (app/services.py: balances, settlement, availability, uploads)
   ↓
SQLite Database (data/rental.db, with constraints and triggers)
   ↓
Local File Storage (uploads/)
```

A **local web application**, not a cloud-hosted website. It listens on `127.0.0.1` only, so only this computer can reach it.

## 4. Project Structure

```
RentalManagement/
├── app/
│   ├── __init__.py        # Flask app factory, error pages, logging
│   ├── config.py          # paths and settings (next to the EXE when packaged)
│   ├── schema.sql         # all tables, constraints and triggers
│   ├── seed.py            # demo data
│   ├── services.py        # business rules (balance, settlement, availability, uploads)
│   ├── security.py        # CSRF protection, login/role guards
│   ├── views/             # routes: auth, customer, files, staff/ (master, contracts, billing, requests)
│   ├── templates/         # HTML pages (customer/, staff/)
│   └── static/style.css
├── scripts/               # init_db.py, seed_demo.py, reset_db.py
├── tests/                 # automated tests
├── packaging/             # "Reset Demo Data.bat" for the release folder
├── run.py                 # entry point
├── RentalManagement.spec  # PyInstaller (onedir) build definition
├── build_exe.bat          # one-click build on Windows
├── requirements.txt
└── README.md
```
Created at run time (not in source control): `data/`, `uploads/`, `logs/`, `backups/`.

---

# PART A: Developer Setup

*(Only developers need this. Final users go to Part B.)*

## 5. Requirements for Development
- Python 3.13 (other 3.x versions were not tested)
- pip

```
pip install -r requirements.txt
```

## 6. How to Run During Development
```
python run.py
```
The server starts on port **5000** (or the next free port if 5000 is busy), prints the address, and opens your browser. Set the environment variable `RENTAL_NO_BROWSER=1` to stop the browser opening. Press Ctrl+C to stop.

## 7. Database Setup
- **File:** `data/rental.db`. Uploads go to `uploads/`; the session secret key is `data/secret.key`.
- **Created automatically:** yes. On first start, if no database exists, `python run.py` creates it **with demo data**.
- **Tables (15):** property, unit, staff, customer, user_account, rental_request, contract, move_out_request, invoice, payment, repair_request, extension_request, damage_record, incident_log, attachment.
- **Commands:**
  ```
  python -m scripts.init_db     # empty tables only (no accounts); refuses if a database exists
  python -m scripts.seed_demo   # demo data; refuses if a database exists
  python -m scripts.reset_db    # back up data/ and uploads/ to backups/<time>/, then rebuild demo data
  python run.py --reset-demo    # same as reset_db (this is what the EXE uses)
  ```
- **Rules enforced by the database itself:** no overlapping Active contracts for one unit; verified/rejected payments cannot be edited; historical rows (contracts, invoices, payments, repairs, incidents, extensions, damage records, move-outs, attachments, rental requests) cannot be deleted. Wrong damage deductions are *voided* with a reason, not deleted.

## 8. Demo Accounts

Demo/test credentials only. Not real people.

| Role | Username | Password |
|---|---|---|
| Staff (Manager) | `staff1` | `staff1234` |
| Staff (Technician) | `staff2` | `staff1234` |
| Customer (active contract, partly-paid invoice, pending payment) | `customer1` | `customer1234` |
| Customer (waiting and approved rental requests, no contract) | `customer2` | `customer1234` |
| Customer (one ended contract, for tenant history) | `customer3` | `customer1234` |

New customers can also self-register at `/register`; staff can create customer logins when adding a customer.

## 9. Testing
```
python -m unittest discover -s tests -t .
```
59 tests, all passing (Linux, Python 3.13). They cover: overlap prevention (insert and update), no-delete triggers, payment finality, nullable staff columns; verified-only balances, partial payments, overpayment refusal, deposit refund (positive and negative), voided damages; availability vs. `UNIT.status`; customer/staff permission separation and per-customer ownership; duplicate ID-card detection; rental request → contract flow; payment upload validation (type, fake file content, 5 MB limit, proof required); invoices; repair and extension lifecycles; move-out settlement (refund, amount due, collection); incidents; and a page-render test of every main screen.

Not covered by tests: the Windows EXE and the browser auto-open.

## 10. Building the Windows EXE

On a Windows machine with Python 3.13:
```
build_exe.bat
```
which runs `pip install -r requirements.txt pyinstaller`, runs the tests, then:
```
pyinstaller RentalManagement.spec --noconfirm --clean
```
Output: `dist\RentalManagement\` (the script also copies `Reset Demo Data.bat` and this README into it). Test it on a Windows machine **without Python installed**.

**Packaging mode: `--onedir`** (the spec builds a one-folder app). Chosen for demonstration reliability, not smallest size:
- starts faster (`--onefile` unpacks itself to a temp folder on every launch);
- fewer antivirus false positives;
- `data/` and `uploads/` sit visibly next to the EXE, so data persists and is easy to back up;
- easier to diagnose missing files.

---

# PART B: Normal User Setup (Windows EXE)

## 11. Running the Application

You do **not** need to install Python, Flask, pip or SQLite. You do not need Command Prompt.

1. Extract the release folder (if it came as a ZIP).
2. Double-click **`RentalManagement.exe`**.
3. A black console window opens and the application starts (a few seconds).
4. Your browser opens automatically. If not, open the address printed in the window, normally `http://127.0.0.1:5000`.
5. Log in with a demo account (section 8).

To stop: close the black console window.

## 12. Release Folder Structure
```
RentalManagement/
├── RentalManagement.exe
├── _internal/            # required runtime files: do not delete
├── Reset Demo Data.bat
├── README.md
├── data/                 # created on first run: database. Do not delete
├── uploads/              # created on first run: uploaded files. Do not delete
├── logs/                 # created on first run: app.log, startup-error.log
└── backups/              # created only when demo data is reset
```

## 13. Data Storage
| What | Where |
|---|---|
| Database | `data\rental.db` |
| Uploaded files | `uploads\` |
| Logs | `logs\app.log` (startup failures: `logs\startup-error.log`) |

Data stays after closing and reopening the app. **Backup:** close the app, then copy the `data` and `uploads` folders somewhere safe, before every demonstration.

Uploads: JPG, JPEG, PNG or PDF, at most 5 MB per file.

## 14. Resetting Demo Data
Close the application, then double-click **`Reset Demo Data.bat`** and type `YES`. It saves the current `data` and `uploads` to `backups\<date-time>\`, then creates a fresh database with the demo accounts and sample properties, units, contracts, invoices, repairs, etc.

## 15. Troubleshooting

| Problem | What to do |
|---|---|
| **Application does not open** | Check that the console window is open (or `RentalManagement.exe` in Task Manager). Read `logs\startup-error.log` and `logs\app.log`. |
| **Browser does not open** | Open the address shown in the console window (normally `http://127.0.0.1:5000`) in Chrome/Edge. |
| **Port already in use** | Nothing to do: the app automatically uses the next free port (5001, 5002, …). The console shows the actual address. |
| **Database problem** | Close the app, replace `data\` with your backup, or run `Reset Demo Data.bat`. |
| **Upload fails** | Use JPG, PNG or PDF files up to 5 MB each. |
| **Windows security warning** | Windows may warn because this is a locally packaged university application without a commercial signature. Choose "More info" → "Run anyway" for this app only. Never disable Windows security globally. |

---

## 16. How to Use the Application

**Customer:** Login → browse available units → submit rental request → staff contact you → contract created → view invoice → submit payment with slip (status *Pending Verification*) → staff verify → receipt; submit repair / extension requests when needed; submit move-out notice.

**Staff:** Login → review rental request (Contacted / Approved / Rejected) → create contract from an *Approved* request (tick that the customer signed) → issue monthly invoice → verify or reject payments → manage repairs and extension requests → process move-out: record damage deductions, finalize settlement.

## 17. Important Design Notes
- Flask runs locally; SQLite is the database; uploaded files are stored locally; no internet is needed.
- Unit availability is `UNIT.status = 'available'` **and** no overlapping Active / Move-Out Requested contract. Overlaps are blocked by the application and by database triggers.
- Invoice total = rent + water + electricity. Outstanding = total − **verified** payments. Partial payments are supported; pending and rejected payments never reduce the balance.
- Deposit refund = deposit − valid (non-voided) deductions − outstanding invoices. If negative, the contract becomes *Amount Due* until staff mark the amount as collected.
- Customer and staff permissions are separated; customers only see their own records; incident files are staff-only.
- Historical records are never deleted (database triggers); mistakes are voided or superseded.
- Forms use CSRF tokens; passwords are hashed.

## 18. Use Case Coverage

"Complete" = implemented and covered by the automated tests or page-render tests on Linux. It does not yet include Windows EXE verification.

| Use Case | Feature / Module | Actor | Status |
|---|---|---|---|
| UC-01 | Rental request | Customer | Complete |
| UC-02 | Property & unit management | Staff | Complete |
| UC-03 | Customer management | Staff | Complete |
| UC-04 | Submit payment evidence | Customer | Complete |
| UC-05 | View outstanding balance | Customer | Complete |
| UC-06 | Extension / renovation request | Customer | Complete |
| UC-07 | Invoicing & payment verification / receipt | Staff | Complete |
| UC-08 | Repair management | Staff | Complete |
| UC-09 | Review extension requests | Staff | Complete |
| UC-10 | End contract & deposit settlement | Staff | Complete |
| UC-11 | Submit repair request | Customer | Complete |
| UC-12 | Move-out notice | Customer | Complete |
| UC-13 | Create & start contract | Staff | Complete |
| UC-14 | Tenant history | Staff | Complete |
| UC-15 | Incident logging | Staff | Complete |

## 19. University Project Information
```
Project:      Rental Management System (ระบบเช่าบ้าน)
Course:       Software Analysis
University:   Kasetsart University
Team Members: 6710450856 Trai Pringsulaka
              6710451275 Wattanan Jangsuk
              Name Surname
```

## Before You Submit
- [x] On Windows: run `build_exe.bat`; confirm `dist\RentalManagement\RentalManagement.exe` exists.
- [x] Copy the folder to a Windows PC **without Python**; double-click the EXE; browser opens; log in as `staff1` and `customer1`.
- [x] Upload a payment slip, verify it as staff, close and reopen the EXE: data is still there.
- [x] Run `Reset Demo Data.bat`; accounts work afterwards; a `backups\` folder appears.
- [x] Occupy port 5000 and start the EXE: it uses 5001.
- [x] If anything above differs from this README, fix the README.
- [ ] Fill in the project information (section 19).
