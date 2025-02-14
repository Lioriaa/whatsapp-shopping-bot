from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import sqlite3
import re

app = Flask(__name__)
DB_PATH = 'shopping_list.db'

# קומפילציה של תבנית לזיהוי פקודות הסרה (קניתי, סיימתי, תמחק)
removal_pattern = re.compile(
    r"^(קניתי|סיימתי|תמחק)\s+(?:(\d+|[^\s]+)\s+)?(.+)$", re.IGNORECASE | re.UNICODE
)

# מיפוי מספרים מילוליים למספרים (כולל צורות זכר ונקבה)
NUM_MAPPING = {
    'אחד': 1,
    'אחת': 1,
    'שני': 2,
    'שתי': 2,
    'שתיים': 2,
    'שניים': 2,
    'שלוש': 3,
    'שלושה': 3,
    'ארבע': 4,
    'ארבעה': 4,
    'חמש': 5,
    'חמשה': 5,
    'שש': 6,
    'ששה': 6,
    'שבע': 7,
    'שבעה': 7,
    'שמונה': 8,
    'תשע': 9,
    'תשעה': 9,
    'עשר': 10,
    'עשרה': 10
}

# אתחול מסד הנתונים – עמודת quantity כמספר שלם
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                department TEXT NOT NULL
            )
        ''')
        conn.commit()

init_db()

# פונקציה לנירמול שם המוצר (להפיכת צורות רבים לצורת יחיד – חוק פשוט)
def normalize_item_name(name):
    n = name.strip().lower()
    n = n.replace(",", "")
    # חוקים פשוטים לנירמול: אם מסתיים ב-"ים" או "ות" – מסירים
    if len(n) > 3:
        if n.endswith("ים"):
            n = n[:-2]
        elif n.endswith("ות"):
            n = n[:-2]
        elif n.endswith("יות"):
            n = n[:-3] + "יה"
    return n

# סיווג מוצרים למחלקות על בסיס מילות מפתח (העובדות עם צורת היחיד)
DEPARTMENTS = {
    'ירקות ופירות': ['ירק', 'פירות', 'תפוח', 'בננה', 'אגס', 'תות', 'כרוב', 'גזר', 'עגבניה', 'עגבניות'],
    'בשר ודגים': ['בשר', 'סטייק', 'עוף', 'דג', 'נתח', 'שיפוד'],
    'מוצרי חלב': ['חלב', 'גבינה', 'יוגורט', 'חמאה', 'קוטג׳'],
    'מאפים': ['לחם', 'מאפה', 'בייגל', 'קרואסון', 'פיצה'],
    'משקאות': ['מים', 'משקה', 'קולה', 'פחית', 'מיץ'],
    'מזווה': ['סוכר', 'מלח', 'תבלין', 'שמרים', 'אורז', 'פסטה', 'שמן']
}
DEFAULT_DEPARTMENT = 'שונות'

def classify_item(name):
    lower_name = name.lower()
    for dept, keywords in DEPARTMENTS.items():
        for keyword in keywords:
            if keyword in lower_name:
                return dept
    return DEFAULT_DEPARTMENT

def parse_quantity(q_str):
    if not q_str:
        return 1
    q_str = q_str.strip()
    try:
        return int(q_str)
    except ValueError:
        return NUM_MAPPING.get(q_str.lower(), 1)

def parse_item_line(line):
    """
    מפרק שורת קלט להוספת פריט:
      - אם יש פסיק, מפצלים לשם ולקמות.
      - אחרת, בודקים אם המילה הראשונה היא כמות (מספר או מילולי).
    """
    if "," in line:
        parts = line.split(",", 1)
        name = parts[0].strip()
        qty = parse_quantity(parts[1].strip())
        return name, qty
    else:
        tokens = line.split()
        if tokens and (tokens[0].isdigit() or tokens[0].lower() in NUM_MAPPING):
            qty = parse_quantity(tokens[0])
            name = " ".join(tokens[1:])
            return name, qty
        else:
            return line, 1

def add_item(name, quantity):
    """
    מוסיף פריט או מעדכן כמות קיימת.
    אם המוצר קיים (לפי שם מנורמל), מתווספת הכמות החדשה למספר הקיים.
    """
    norm_name = normalize_item_name(name)
    department = classify_item(norm_name)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, quantity FROM items WHERE name COLLATE NOCASE = ?", (norm_name,))
        row = cursor.fetchone()
        if row:
            new_quantity = int(row[1]) + quantity
            cursor.execute("UPDATE items SET quantity=? WHERE id=?", (new_quantity, row[0]))
        else:
            cursor.execute("INSERT INTO items (name, quantity, department) VALUES (?, ?, ?)",
                           (norm_name, quantity, department))
        conn.commit()

def partial_remove_item(name, quantity_removed):
    """
    מסיר כמות מסוימת מהמלאי:
      - אם לאחר ההסרה נותרות יחידות – מעדכן את הכמות.
      - אחרת, מוחק את המוצר מהרשימה.
    """
    norm_name = normalize_item_name(name)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, quantity FROM items WHERE name COLLATE NOCASE = ?", (norm_name,))
        row = cursor.fetchone()
        if row:
            current_quantity = int(row[1])
            new_quantity = current_quantity - quantity_removed
            if new_quantity > 0:
                cursor.execute("UPDATE items SET quantity=? WHERE id=?", (new_quantity, row[0]))
            else:
                cursor.execute("DELETE FROM items WHERE id=?", (row[0],))
        conn.commit()

def remove_all_items():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM items")
        conn.commit()

def list_items():
    """
    מציג את רשימת הקניות בטבלה מסודרת, כאשר הטבלה מוצגת בתוך בלוק קוד (monospace).
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, quantity, department FROM items ORDER BY department, name")
        rows = cursor.fetchall()
    if not rows:
        return "רשימת הקניות ריקה."
    departments = {}
    for name, quantity, department in rows:
        departments.setdefault(department, []).append((name, quantity))
    message = "רשימת הקניות הנוכחית:\n"
    message += "```\n"
    for dept in sorted(departments.keys()):
        message += f"{dept}:\n"
        message += "-" * 30 + "\n"
        message += f"{'מוצר':<20}{'כמות':>5}\n"
        message += "-" * 30 + "\n"
        for item_name, qty in departments[dept]:
            message += f"{item_name:<20}{qty:>5}\n"
        message += "-" * 30 + "\n"
    message += "```"
    return message

def help_text():
    return (
        "אפשרויות המערכת:\n"
        "1. להוספת פריט: כתבו את שם הפריט עם אפשרות לציון כמות. לדוגמא:\n"
        "   - 'תפוח, 3' או 'תפוח, שלושה'\n"
        "   - 'שני תפוחים' או '3 תפוחים'\n"
        "   (אם הפריט קיים, הכמות מתעדכנת על ידי הוספת הכמות החדשה)\n\n"
        "2. להסרת פריט או עדכון כמות: כתבו 'קניתי [שם הפריט]' להסרת יחידה אחת, או 'קניתי [שם הפריט] 2' להסרת 2 יחידות.\n"
        "   לדוגמא: 'קניתי תפוח' להסרת 1 יחידה או 'קניתי תפוחים 2' להסרת 2 יחידות.\n\n"
        "3. להסרת כל הפריטים: כתבו 'קניתי הכל'.\n\n"
        "4. להצגת רשימת הקניות: שלחו הודעה עם פריטים להוספה או כל הודעה אחרת.\n\n"
        "5. להצגת עזרה: כתבו 'עזרה'."
    )

def parse_message(body):
    """
    מנתח את הודעת המשתמש וקובע האם להוסיף פריט, להסיר (חלקית) או להציג עזרה.
    - במידה וההודעה היא 'עזרה' או 'קניתי הכל' – מטפלים בהתאם.
    - בכל שורה, אם הפקודה מתחילה באחד ממילות ההסרה (זיהוי באמצעות regex) – מבצעים הסרה,
      אחרת – מבצעים הוספה.
    """
    body = body.strip()
    lower = body.lower().strip()
    if lower == "עזרה":
        return help_text()
    if lower == "קניתי הכל":
        remove_all_items()
        return "מעולה! ניקיתי את רשימת הקניות.\n" + list_items()
    response = ""
    lines = body.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = removal_pattern.match(line)
        if m:
            # זיהוי פקודת הסרה
            qty_str = m.group(2)
            product_str = m.group(3)
            qty = parse_quantity(qty_str) if qty_str else 1
            partial_remove_item(product_str, qty)
            response += f"הסרתי {qty} מ'{normalize_item_name(product_str)}'.\n"
        else:
            # פקודת הוספה
            name, qty = parse_item_line(line)
            add_item(name, qty)
            response += f"הוספתי {qty} מ'{normalize_item_name(name)}'.\n"
    response += "\n" + list_items()
    return response

@app.route("/whatsapp", methods=['POST'])
def whatsapp_webhook():
    body = request.values.get('Body', '')
    response_text = parse_message(body)
    resp = MessagingResponse()
    resp.message(response_text)
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)
