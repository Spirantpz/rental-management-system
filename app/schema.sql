-- Rental Management System: SQLite schema (corrected ER)
PRAGMA foreign_keys = ON;

CREATE TABLE property (
  property_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  address       TEXT NOT NULL,
  property_type TEXT NOT NULL
);

CREATE TABLE unit (
  unit_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  property_id INTEGER NOT NULL REFERENCES property(property_id) ON DELETE RESTRICT,
  unit_no     TEXT NOT NULL,
  rent_price  REAL NOT NULL CHECK (rent_price >= 0),
  -- 'available' only means "open for rent". Occupancy is derived from contracts.
  status      TEXT NOT NULL DEFAULT 'available'
              CHECK (status IN ('available','maintenance','inactive')),
  UNIQUE (property_id, unit_no)
);

CREATE TABLE staff (
  staff_id  INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT NOT NULL,
  role      TEXT NOT NULL,
  phone     TEXT
);

CREATE TABLE customer (
  customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name   TEXT NOT NULL,
  phone       TEXT,
  id_card_no  TEXT NOT NULL UNIQUE,
  address     TEXT
);

-- Authentication is kept separate from the CUSTOMER / STAFF profiles.
CREATE TABLE user_account (
  user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('customer','staff')),
  customer_id   INTEGER UNIQUE REFERENCES customer(customer_id) ON DELETE RESTRICT,
  staff_id      INTEGER UNIQUE REFERENCES staff(staff_id) ON DELETE RESTRICT,
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK ((role = 'customer' AND customer_id IS NOT NULL AND staff_id IS NULL)
      OR (role = 'staff'    AND staff_id IS NOT NULL AND customer_id IS NULL))
);

-- UC-01
CREATE TABLE rental_request (
  request_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id           INTEGER NOT NULL REFERENCES customer(customer_id) ON DELETE RESTRICT,
  unit_id               INTEGER REFERENCES unit(unit_id) ON DELETE RESTRICT,
  desired_property_type TEXT,
  desired_start_date    TEXT NOT NULL,
  desired_end_date      TEXT NOT NULL,
  requirements          TEXT,
  status                TEXT NOT NULL DEFAULT 'Waiting for Staff'
                        CHECK (status IN ('Waiting for Staff','Contacted','Approved','Rejected','Converted','Cancelled')),
  created_date          TEXT NOT NULL,
  handled_by_staff_id   INTEGER REFERENCES staff(staff_id) ON DELETE RESTRICT,
  handled_date          TEXT,
  staff_note            TEXT,
  CHECK (desired_end_date >= desired_start_date)
);

CREATE TABLE contract (
  contract_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  rental_request_id INTEGER NOT NULL UNIQUE REFERENCES rental_request(request_id) ON DELETE RESTRICT,
  customer_id       INTEGER NOT NULL REFERENCES customer(customer_id) ON DELETE RESTRICT,
  unit_id           INTEGER NOT NULL REFERENCES unit(unit_id) ON DELETE RESTRICT,
  staff_id          INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE RESTRICT,
  start_date        TEXT NOT NULL,
  end_date          TEXT NOT NULL,
  deposit_amount    REAL NOT NULL CHECK (deposit_amount >= 0),
  status            TEXT NOT NULL DEFAULT 'Active'
                    CHECK (status IN ('Active','Move-Out Requested','Amount Due','Ended')),
  move_out_date     TEXT,   -- actual / final move-out date
  refund_amount     REAL,   -- negative = customer still owes money
  settlement_note   TEXT,
  CHECK (end_date >= start_date)
);

-- UC-12
CREATE TABLE move_out_request (
  move_out_id             INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id             INTEGER NOT NULL REFERENCES contract(contract_id) ON DELETE RESTRICT,
  requested_move_out_date TEXT NOT NULL,
  reason                  TEXT,
  early_notice            INTEGER NOT NULL DEFAULT 0,
  status                  TEXT NOT NULL DEFAULT 'Pending'
                          CHECK (status IN ('Pending','Acknowledged','Completed','Cancelled')),
  created_date            TEXT NOT NULL,
  created_by_user_id      INTEGER REFERENCES user_account(user_id) ON DELETE RESTRICT,
  handled_by_staff_id     INTEGER REFERENCES staff(staff_id) ON DELETE RESTRICT,
  handled_date            TEXT,
  staff_note              TEXT
);

CREATE TABLE invoice (
  invoice_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id  INTEGER NOT NULL REFERENCES contract(contract_id) ON DELETE RESTRICT,
  period       TEXT NOT NULL,           -- 'YYYY-MM'
  rent_fee     REAL NOT NULL CHECK (rent_fee >= 0),
  water_fee    REAL NOT NULL DEFAULT 0 CHECK (water_fee >= 0),
  electric_fee REAL NOT NULL DEFAULT 0 CHECK (electric_fee >= 0),
  due_date     TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'Unpaid' CHECK (status IN ('Unpaid','Partially Paid','Paid')),
  UNIQUE (contract_id, period)
);

-- UC-04 / UC-07: only Verified payments reduce the invoice balance.
CREATE TABLE payment (
  payment_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id            INTEGER NOT NULL REFERENCES invoice(invoice_id) ON DELETE RESTRICT,
  amount                REAL NOT NULL CHECK (amount > 0),
  payment_date          TEXT NOT NULL,
  payment_method        TEXT,
  note                  TEXT,
  status                TEXT NOT NULL DEFAULT 'Pending Verification'
                        CHECK (status IN ('Pending Verification','Verified','Rejected')),
  submitted_by_user_id  INTEGER REFERENCES user_account(user_id) ON DELETE RESTRICT,
  created_at            TEXT NOT NULL DEFAULT (datetime('now')),
  verified_by_staff_id  INTEGER REFERENCES staff(staff_id) ON DELETE RESTRICT,
  verified_date         TEXT,
  receipt_no            TEXT UNIQUE,
  reject_reason         TEXT,
  CHECK (status <> 'Verified' OR (verified_by_staff_id IS NOT NULL AND receipt_no IS NOT NULL))
);

CREATE TABLE repair_request (
  repair_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id       INTEGER NOT NULL REFERENCES contract(contract_id) ON DELETE RESTRICT,
  assigned_staff_id INTEGER REFERENCES staff(staff_id) ON DELETE RESTRICT,
  description       TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'Pending'
                    CHECK (status IN ('Pending','In Progress','Awaiting Customer Approval','Completed','Cancelled')),
  created_date      TEXT NOT NULL,
  completed_date    TEXT,
  cost              REAL CHECK (cost IS NULL OR cost >= 0),
  staff_note        TEXT
);

CREATE TABLE extension_request (
  request_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id         INTEGER NOT NULL REFERENCES contract(contract_id) ON DELETE RESTRICT,
  decided_by_staff_id INTEGER REFERENCES staff(staff_id) ON DELETE RESTRICT,
  scope_description   TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'Pending Review'
                      CHECK (status IN ('Pending Review','Approved','Rejected','Needs More Info')),
  condition_or_reason TEXT,
  created_date        TEXT NOT NULL,
  decision_date       TEXT
);

CREATE TABLE damage_record (
  damage_id            INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id          INTEGER NOT NULL REFERENCES contract(contract_id) ON DELETE RESTRICT,
  description          TEXT NOT NULL,
  deduction_amount     REAL NOT NULL CHECK (deduction_amount >= 0),
  recorded_by_staff_id INTEGER REFERENCES staff(staff_id) ON DELETE RESTRICT,
  recorded_date        TEXT,
  is_voided            INTEGER NOT NULL DEFAULT 0,   -- voided instead of deleted
  void_reason          TEXT
);

CREATE TABLE incident_log (
  incident_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id          INTEGER NOT NULL REFERENCES contract(contract_id) ON DELETE RESTRICT,
  responsible_staff_id INTEGER NOT NULL REFERENCES staff(staff_id) ON DELETE RESTRICT,
  incident_date        TEXT NOT NULL,
  description          TEXT NOT NULL,
  resolution_status    TEXT NOT NULL DEFAULT 'Under Investigation'
                       CHECK (resolution_status IN ('Under Investigation','Resolved','Dismissed')),
  resolution_note      TEXT
);

-- Reusable file metadata (the files themselves live in the uploads/ folder).
CREATE TABLE attachment (
  attachment_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type         TEXT NOT NULL
                      CHECK (entity_type IN ('payment','repair','extension','incident','damage','rental_request','move_out','other')),
  entity_id           INTEGER NOT NULL,
  original_name       TEXT NOT NULL,
  stored_name         TEXT NOT NULL UNIQUE,
  mime_type           TEXT NOT NULL,
  size_bytes          INTEGER NOT NULL,
  description         TEXT,
  uploaded_by_user_id INTEGER REFERENCES user_account(user_id) ON DELETE RESTRICT,
  uploaded_at         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_attachment_entity ON attachment(entity_type, entity_id);
CREATE INDEX idx_contract_unit ON contract(unit_id, status);
CREATE INDEX idx_invoice_contract ON invoice(contract_id);
CREATE INDEX idx_payment_invoice ON payment(invoice_id, status);

-- Rule: one unit cannot have two overlapping active contracts.
CREATE TRIGGER trg_contract_no_overlap_ins BEFORE INSERT ON contract
WHEN NEW.status IN ('Active','Move-Out Requested')
BEGIN
  SELECT RAISE(ABORT, 'Overlapping active contract for this unit')
  WHERE EXISTS (SELECT 1 FROM contract c
                WHERE c.unit_id = NEW.unit_id
                  AND c.status IN ('Active','Move-Out Requested')
                  AND c.start_date <= NEW.end_date AND c.end_date >= NEW.start_date);
END;

CREATE TRIGGER trg_contract_no_overlap_upd BEFORE UPDATE OF unit_id, start_date, end_date, status ON contract
WHEN NEW.status IN ('Active','Move-Out Requested')
BEGIN
  SELECT RAISE(ABORT, 'Overlapping active contract for this unit')
  WHERE EXISTS (SELECT 1 FROM contract c
                WHERE c.unit_id = NEW.unit_id AND c.contract_id <> NEW.contract_id
                  AND c.status IN ('Active','Move-Out Requested')
                  AND c.start_date <= NEW.end_date AND c.end_date >= NEW.start_date);
END;

-- Rule: historical records cannot be deleted (even by mistake).
CREATE TRIGGER trg_no_delete_contract  BEFORE DELETE ON contract          BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_invoice   BEFORE DELETE ON invoice           BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_payment   BEFORE DELETE ON payment           BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_repair    BEFORE DELETE ON repair_request    BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_incident  BEFORE DELETE ON incident_log      BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_extension BEFORE DELETE ON extension_request BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_damage    BEFORE DELETE ON damage_record     BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_moveout   BEFORE DELETE ON move_out_request  BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_attach    BEFORE DELETE ON attachment        BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;
CREATE TRIGGER trg_no_delete_request   BEFORE DELETE ON rental_request    BEGIN SELECT RAISE(ABORT, 'Historical records cannot be deleted'); END;

-- Rule: a verified or rejected payment is final.
CREATE TRIGGER trg_payment_final BEFORE UPDATE ON payment
WHEN OLD.status IN ('Verified','Rejected')
 AND (NEW.status <> OLD.status OR NEW.amount <> OLD.amount OR NEW.invoice_id <> OLD.invoice_id)
BEGIN SELECT RAISE(ABORT, 'A verified or rejected payment cannot be changed'); END;
