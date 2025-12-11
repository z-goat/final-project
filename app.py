import os
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from helpers import login_required, gbp

app = Flask(__name__)
app.jinja_env.filters["gbp"] = gbp
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

db = SQL("sqlite:///project.db")


@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# -------------------------
# ROUTES
# -------------------------


@app.route("/")
@login_required
def index():
    """Dashboard with Revenue, Sorting, and Projects"""
    user_id = session["user_id"]

    # 1. Calculate Total Revenue (Sum of all project values for this user)
    # We join clients to ensure we only count this user's projects
    rev_data = db.execute("""
        SELECT SUM(value) as total
        FROM projects
        JOIN clients ON projects.client_id = clients.id
        WHERE clients.user_id = ?
    """, user_id)

    total_revenue = rev_data[0]["total"]
    if total_revenue is None:
        total_revenue = 0

    # 2. Sorting Logic
    sort_by = request.args.get("sort", "deadline")  # Default to deadline

    if sort_by == "importance":
        order_sql = """
            CASE importance
                WHEN 'High' THEN 1
                WHEN 'Medium' THEN 2
                WHEN 'Low' THEN 3
                ELSE 4
            END
        """
    elif sort_by == "client":
        order_sql = "clients.name ASC"
    elif sort_by == "value":
        order_sql = "projects.value DESC"
    else:
        # Default: Closest deadline first (NULLs last)
        order_sql = "projects.deadline ASC NULLS LAST"

    # 3. Fetch Projects
    projects = db.execute(f"""
        SELECT projects.*, clients.name as client_name
        FROM projects
        JOIN clients ON projects.client_id = clients.id
        WHERE clients.user_id = ?
        ORDER BY {order_sql}
    """, user_id)

    # 4. Fetch Clients (for the list)
    clients = db.execute("SELECT * FROM clients WHERE user_id = ?", user_id)

    return render_template("dashboard.html",
                           projects=projects,
                           clients=clients,
                           total_revenue=total_revenue,
                           current_sort=sort_by)


@app.route("/addclient", methods=["GET", "POST"])
@login_required
def add_client():
    if request.method == "POST":
        name = request.form.get("name")
        company = request.form.get("company")
        email = request.form.get("email")
        phone = request.form.get("phone")
        status = request.form.get("status")

        if not name:
            flash("Client Name is required", "danger")
            return redirect("/addclient")

        db.execute("""
            INSERT INTO clients (user_id, name, company, email, phone, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, session["user_id"], name, company, email, phone, status)

        flash("Client added!", "success")
        return redirect("/")

    return render_template("add_client.html")


@app.route("/addproject", methods=["GET", "POST"])
@login_required
def add_project():
    if request.method == "POST":
        client_id = request.form.get("client_id")
        name = request.form.get("project_name")
        description = request.form.get("description")
        status = request.form.get("status")
        importance = request.form.get("importance")

        # Handle optional Numeric field
        value = request.form.get("value")
        if not value:
            value = 0

        # Handle optional Date field
        deadline = request.form.get("deadline")
        if not deadline:
            deadline = None

        if not client_id or not name:
            flash("Client and Project Name are required", "danger")
            return redirect("/addproject")

        # Security Check
        check = db.execute("SELECT id FROM clients WHERE id = ? AND user_id = ?",
                           client_id, session["user_id"])
        if not check:
            flash("Invalid Client", "danger")
            return redirect("/")

        db.execute("""
            INSERT INTO projects (client_id, name, description, value, status, importance, deadline)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, client_id, name, description, value, status, importance, deadline)

        flash("Project added!", "success")
        return redirect("/")

    else:
        clients = db.execute("SELECT * FROM clients WHERE user_id = ?", session["user_id"])
        return render_template("add_project.html", clients=clients)


@app.route("/client/<int:client_id>")
@login_required
def client_details(client_id):
    client = db.execute("SELECT * FROM clients WHERE id = ? AND user_id = ?",
                        client_id, session["user_id"])
    if not client:
        return redirect("/")
    client = client[0]

    projects = db.execute(
        "SELECT * FROM projects WHERE client_id = ? ORDER BY deadline ASC", client_id)

    return render_template("client_details.html", client=client, projects=projects)


@app.route("/delete_project/<int:project_id>", methods=["POST"])
@login_required
def delete_project(project_id):
    db.execute("""
        DELETE FROM projects
        WHERE id = ? AND client_id IN (SELECT id FROM clients WHERE user_id = ?)
    """, project_id, session["user_id"])
    flash("Project deleted", "success")
    return redirect("/")


@app.route("/delete_client/<int:client_id>", methods=["POST"])
@login_required
def delete_client(client_id):
    db.execute("DELETE FROM clients WHERE id = ? AND user_id = ?", client_id, session["user_id"])
    flash("Client deleted", "success")
    return redirect("/")


# --- Keep your Login/Register Routes Below Here ---
# (I assume you have these from the previous step. If not, paste them back in)
@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    if request.method == "POST":
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return render_template("login.html")
        session["user_id"] = rows[0]["id"]
        return redirect("/")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            id = db.execute("INSERT INTO users (username, hash) VALUES (?, ?)",
                            request.form.get("username"), generate_password_hash(request.form.get("password")))
            session["user_id"] = id
            return redirect("/")
        except:
            return render_template("register.html")
    return render_template("register.html")


@app.route("/edit_client/<int:client_id>", methods=["GET", "POST"])
@login_required
def edit_client(client_id):
    """Edit an existing client"""

    # 1. Security Check: Get client ensuring it belongs to user
    client = db.execute("SELECT * FROM clients WHERE id = ? AND user_id = ?",
                        client_id, session["user_id"])
    if not client:
        flash("Client not found", "danger")
        return redirect("/")

    client = client[0]

    # 2. Handle Form Submission
    if request.method == "POST":
        name = request.form.get("name")
        company = request.form.get("company")
        email = request.form.get("email")
        phone = request.form.get("phone")
        status = request.form.get("status")

        if not name:
            flash("Client Name cannot be empty", "danger")
            return redirect(f"/edit_client/{client_id}")

        db.execute("""
            UPDATE clients
            SET name = ?, company = ?, email = ?, phone = ?, status = ?
            WHERE id = ?
        """, name, company, email, phone, status, client_id)

        flash("Client updated successfully!", "success")
        return redirect(f"/client/{client_id}")

    # 3. Show Form (GET)
    return render_template("edit_client.html", client=client)

@app.route("/edit_project/<int:project_id>", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    """Edit an existing project"""

    # 1. Security Check: Join tables to ensure client belongs to user
    project = db.execute("""
        SELECT projects.*
        FROM projects
        JOIN clients ON projects.client_id = clients.id
        WHERE projects.id = ? AND clients.user_id = ?
    """, project_id, session["user_id"])

    if not project:
        flash("Project not found", "danger")
        return redirect("/")

    project = project[0]

    if request.method == "POST":
        name = request.form.get("project_name")
        description = request.form.get("description")
        status = request.form.get("status")
        importance = request.form.get("importance")

        # Optional fields
        value = request.form.get("value")
        if not value: value = 0

        deadline = request.form.get("deadline")
        if not deadline: deadline = None

        if not name:
            flash("Project Name required", "danger")
            return redirect(f"/edit_project/{project_id}")

        db.execute("""
            UPDATE projects
            SET name = ?, description = ?, value = ?, status = ?, importance = ?, deadline = ?
            WHERE id = ?
        """, name, description, value, status, importance, deadline, project_id)

        flash("Project updated!", "success")
        # Redirect back to the client's page
        return redirect(f"/client/{project['client_id']}")

    return render_template("edit_project.html", project=project)

