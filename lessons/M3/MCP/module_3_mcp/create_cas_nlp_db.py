import sqlite3

# Connect to the SQLite database (creates if not existing)
conn = sqlite3.connect("cas_nlp.db")
cursor = conn.cursor()

# Drop and recreate table to refresh contents
cursor.execute("DROP TABLE IF EXISTS modules")

cursor.execute("""
CREATE TABLE modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_code TEXT,
    title TEXT,
    date TEXT,
    time TEXT,
    location TEXT,
    lecturers TEXT,
    comments TEXT,
    project_info TEXT
)
""")

modules = [
    ("M1", "NLP 1", "2025-08-19 - 2025-08-22", "09:15 - 12:30",
     "Tue: Room 120, UniM; Wed-Fri: Room 016, UniM",
     "Dr. Christa Schneider & Martin Ritzmann",
     "On Friday there will be an apero at 5 pm",
     "Project Report deadline: TBD (2025-09-30)"),

    ("M2", "NLP 2", "2025-08-26 - 2025-08-29", "09:15 - 12:30 (4 half days, afternoons for self-study)",
     "Mon-Fri: Room 128, UniM",
     "Dr. Christa Schneider & Martin Ritzmann",
     "",
     "Project Presentation: 2025-10-03"),

    ("M3", "Neural Networks", "2025-10-06 - 2025-10-10", "08:30 - 12:30; 17:00 - 19:00",
     "Lago Maggiore, Italy",
     "PD Dr. S. Haug, Dr. M. Vladymyrov, Ahmad Alhineidi",
     "Monday arrival day (starts 17:00); Friday departure day (ends 12:30)",
     "Project Presentation TBD (week 48, online or ExWi)"),

    ("M4", "Transformers", "2025-10-24 – 2025-12-12 (Every Friday)", "15:15 - 17:00",
     "Room B078, ExWi",
     "Dr. Sukanya Nath",
     'Includes "Legal Aspects" lecture (2025-11-14, 08:15 - 12:00, Kuppelraum HG, Christoph Ammon)',
     "Project Deadline: TBD (2025-11-30)"),

    ("M5", "Philosophical and Ethical Aspects of NLP", "2025-10-24 – 2025-12-12 (Every Friday)", "13:15 - 15:00",
     "Room A097, ExWi",
     "Prof. Dr. Dr. C. Beisbart, PD Dr. Vincent Lam",
     "",
     "Project TBD (likely February 2026)"),

    ("M6", "Frontier and Applications", "2026-01-26 - 2026-01-30", "08:30 - 12:30; 17:00 - 19:00",
     "Hotel Regina Mürren (Bernese Oberland)",
     "Paolo Rosso, Dr. M. Vladymyrov, PD Dr. S. Haug",
     "Monday arrival, Friday departure (similar schedule to M3)",
     "Project TBD (likely March 2026)"),

    ("Final", "Final Project", "Deadline: 2026-06-15", "",
     "",
     "PD Dr. S. Haug",
     "",
     "Submit project report PDF + repo link via CAS platform. Late submissions delay diploma."),

    ("Graduation", "Graduation Event", "2026-08-28", "Poster Session: 15:00-16:30; Party: 17:00-open end",
     "ExWi Foyer; LesBar, Münstergasse 63, 3011 Bern",
     "",
     "Deadline registration and poster: 2026-08-23",
     "Includes poster session and graduation celebration.")
]

cursor.executemany("""
INSERT INTO modules (module_code, title, date, time, location, lecturers, comments, project_info)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", modules)

conn.commit()
conn.close()

print("✅ CAS NLP database created successfully with module info!")
