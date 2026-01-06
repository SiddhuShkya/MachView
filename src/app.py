import os
import json
import ee
import tempfile
import zipfile
import requests
import uuid
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from fastkml import kml
import fiona
from shapely.geometry import mapping
from geopy.geocoders import Nominatim
from dotenv import load_dotenv
import threading
import redis

load_dotenv()

# Initialize Redis
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

app = Flask(__name__, template_folder=".", static_folder=".", static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-change-this")
app.config["UPLOAD_FOLDER"] = tempfile.gettempdir()
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max file size
app.config["ALLOWED_EXTENSIONS"] = {"geojson", "kml", "kmz", "zip"}

# Use absolute paths for data directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "satellite_data")
os.makedirs(DATA_DIR, exist_ok=True)

# Global flag to track Earth Engine initialization status
EE_INITIALIZED = False

# Global dictionary to store background tasks
TASKS = {}


# Initialize Earth Engine
def init_ee():
    global EE_INITIALIZED
    
    # Try to load from Redis if env/files are missing
    project_id = os.getenv("PROJECT_ID") or redis_client.get("PROJECT_ID")
    service_account = os.getenv("SERVICE_ACCOUNT") or redis_client.get("SERVICE_ACCOUNT")
    
    # Restore service account key from Redis if missing
    key_path = "service-account-key.json"
    if not os.path.exists(key_path):
        key_content = redis_client.get("SA_KEY_JSON")
        if key_content:
            try:
                with open(key_path, "w") as f:
                    f.write(key_content)
                print("✅ Restored service-account-key.json from Redis")
            except Exception as e:
                print(f"⚠️ Failed to restore key from Redis: {e}")

    # Try service account authentication first
    if service_account and os.path.exists("service-account-key.json"):
        try:
            credentials = ee.ServiceAccountCredentials(
                service_account, "service-account-key.json"
            )
            if project_id:
                ee.Initialize(credentials, project=project_id)
            else:
                ee.Initialize(credentials)
            EE_INITIALIZED = True
            print("✅ Earth Engine initialized with service account")
            return True
        except Exception as e:
            print(f"⚠️  Service account authentication failed: {e}")

    # Try with project ID only (for user authentication)
    if project_id:
        try:
            # Check if already initialized
            try:
                ee.Number(0).getInfo()
                EE_INITIALIZED = True
                print("✅ Earth Engine already initialized")
                return True
            except:  # noqa: E722
                pass

            # Try to initialize with project
            ee.Initialize(project=project_id)
            EE_INITIALIZED = True
            print(f"✅ Earth Engine initialized with project ID: {project_id}")
            return True
        except Exception as e:
            print(f"⚠️  Project ID initialization failed: {e}")
            print("💡 Trying interactive authentication...")

    # Try interactive authentication as last resort
    try:
        # Check if already initialized
        try:
            ee.Number(0).getInfo()
            EE_INITIALIZED = True
            print("✅ Earth Engine already initialized")
            return True
        except:  # noqa: E722
            pass

        print("⚠️  Attempting interactive authentication...")
        print("💡 If this fails, run 'earthengine authenticate' in your terminal first")
        ee.Authenticate()
        ee.Initialize()
        EE_INITIALIZED = True
        print("✅ Earth Engine initialized with interactive authentication")
        return True
    except Exception as e:
        print(f"❌ Earth Engine initialization failed: {e}")
        print("\n" + "=" * 60)
        print("⚠️  EARTH ENGINE NOT INITIALIZED")
        print("=" * 60)
        print("The app will run, but satellite data fetching will not work.")
        print("\nTo fix this:")
        print("1. Run 'earthengine authenticate' in your terminal")
        print("2. Or set up a service account with service-account-key.json")
        print("3. Or set PROJECT_ID in your .env file")
        print("=" * 60 + "\n")
        EE_INITIALIZED = False
        return False


# Initialize on startup
init_ee()


@app.route("/api/ee_status", methods=["GET"])
def ee_status():
    """Check Earth Engine initialization status and Redis-cached config."""
    global EE_INITIALIZED
    
    # Check if configuration exists in env, file, OR Redis
    has_project = bool(os.getenv("PROJECT_ID") or redis_client.get("PROJECT_ID"))
    has_sa = bool(os.getenv("SERVICE_ACCOUNT") or redis_client.get("SERVICE_ACCOUNT"))
    has_key = os.path.exists("service-account-key.json") or bool(redis_client.get("SA_KEY_JSON"))
    
    if not (has_project and has_sa and has_key):
        return jsonify({"initialized": False, "status": "needs_setup"})

    if EE_INITIALIZED:
        try:
            # Test if EE is actually working
            ee.Number(0).getInfo()
            return jsonify({"initialized": True, "status": "ready"})
        except:  # noqa: E722
            EE_INITIALIZED = False
            return jsonify({"initialized": False, "status": "error"})
    
    # If not initialized but has config, try initializing
    if init_ee():
        return jsonify({"initialized": True, "status": "ready"})
        
    return jsonify({"initialized": False, "status": "not_configured"})


@app.route("/api/setup", methods=["POST"])
def setup_credentials():
    """Save credentials to disk AND Redis for persistence across container restarts."""
    try:
        project_id = request.form.get("project_id")
        service_account = request.form.get("service_account")
        
        if not project_id or not service_account:
            return jsonify({"error": "Project ID and Service Account are required"}), 400
            
        if "file" not in request.files:
            return jsonify({"error": "Service account key file is required"}), 400
            
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400
            
        # Save to Redis for Docker persistence
        redis_client.set("PROJECT_ID", project_id)
        redis_client.set("SERVICE_ACCOUNT", service_account)
        
        # Read file content to save in Redis
        file_content = file.read().decode("utf-8")
        redis_client.set("SA_KEY_JSON", file_content)
        
        # Also save to disk for immediate use
        with open(".env", "w") as f:
            f.write(f"PROJECT_ID={project_id}\n")
            f.write(f"SERVICE_ACCOUNT={service_account}\n")
            f.write("SECRET_KEY=your-secret-key-change-this\n")
            
        with open("service-account-key.json", "w") as f:
            f.write(file_content)
        
        # Reload env vars in current process
        os.environ["PROJECT_ID"] = project_id
        os.environ["SERVICE_ACCOUNT"] = service_account
        
        if init_ee():
            return jsonify({"success": True, "message": "Configuration saved and Earth Engine initialized"})
        else:
            return jsonify({"success": False, "error": "Configuration saved but initialization failed. Check credentials."}), 400
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def load_geojson(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)

    # Normalize to FeatureCollection
    if data.get("type") == "FeatureCollection":
        return data
    elif data.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [data]}
    else:
        # Assume it's a geometry or other object that can be wrapped in a Feature
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": data}],
        }


def load_kml(file_path):
    k = kml.KML()
    with open(file_path, "rb") as f:
        k.from_string(f.read().decode("utf-8"))

    features = []
    for doc in k.features():
        for folder in doc.features():
            for f in folder.features():
                geom = mapping(f.geometry)
                features.append({"type": "Feature", "properties": {}, "geometry": geom})

    return {"type": "FeatureCollection", "features": features}


def load_kmz(file_path):
    with zipfile.ZipFile(file_path, "r") as kmz:
        kml_filename = [f for f in kmz.namelist() if f.endswith(".kml")][0]
        kml_content = kmz.read(kml_filename).decode("utf-8")

    k = kml.KML()
    k.from_string(kml_content)

    features = []
    for doc in k.features():
        for folder in doc.features():
            for f in folder.features():
                geom = mapping(f.geometry)
                features.append({"type": "Feature", "properties": {}, "geometry": geom})

    return {"type": "FeatureCollection", "features": features}


def load_shapefile_zip(file_path):
    features = []
    with fiona.open(file_path) as shp:
        for feat in shp:
            features.append(
                {
                    "type": "Feature",
                    "properties": feat["properties"],
                    "geometry": feat["geometry"],
                }
            )

    return {"type": "FeatureCollection", "features": features}


def load_aoi_file(file_path, filename):
    ext = filename.rsplit(".", 1)[1].lower()

    if ext == "geojson":
        return load_geojson(file_path)
    elif ext == "kml":
        return load_kml(file_path)
    elif ext == "kmz":
        return load_kmz(file_path)
    elif ext == "zip":
        # Check if it's a shapefile zip or a batch geojson zip
        is_shapefile = False
        with zipfile.ZipFile(file_path, "r") as z:
            for f in z.namelist():
                if f.endswith(".shp"):
                    is_shapefile = True
                    break
        
        if is_shapefile:
            return load_shapefile_zip(file_path)
        else:
            return load_geojson_zip(file_path)

    return None


def load_geojson_zip(file_path):
    """
    Loads a zip file containing multiple GeoJSON files.
    EXPECTS filename format: {id}_{year}_{month}.geojson
    Example: 273641523489998_2017_October.geojson
    """
    features = []
    
    with zipfile.ZipFile(file_path, "r") as z:
        for filename in z.namelist():
            if not filename.endswith(".geojson") or filename.startswith("__MACOSX") or filename.startswith("."):
                continue
                
            try:
                # Parse filename
                basename = os.path.splitext(os.path.basename(filename))[0]
                parts = basename.split("_")
                
                # Default values
                plot_id = basename
                f_year = None
                f_month = None

                # Optional: Parse id, year, month if pattern matches
                if len(parts) >= 3:
                    f_month = parts[-1]
                    f_year = parts[-2]
                    plot_id = "_".join(parts[:-2])
                    
                # Load content
                content = z.read(filename).decode("utf-8")
                data = json.loads(content)
                if isinstance(data, str):
                    data = json.loads(data)
                        
                # Extract geometry
                geoms = []
                if data.get("type") == "FeatureCollection":
                    for f in data["features"]:
                        geoms.append(f["geometry"])
                elif data.get("type") == "Feature":
                    geoms.append(data["geometry"])
                else:
                    geoms.append(data) # Assume raw geometry
                        
                for geom in geoms:
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "plot_id": plot_id,
                            "custom_year": f_year,
                            "custom_month": f_month,
                            "original_filename": filename
                        },
                        "geometry": geom
                    })
            except Exception as e:
                print(f"Error processing {filename}: {e}")
                continue
                
    return {"type": "FeatureCollection", "features": features}


def mask_s2_clouds(image):
    scl = image.select("SCL")
    mask = scl.neq(3).And(scl.neq(8))
    return image.updateMask(mask)


def mask_l8_clouds(image):
    # Landsat-8 Collection 2 uses QA_PIXEL band
    qa = image.select("QA_PIXEL")
    # Bits 3 and 4 are cloud and cloud shadow
    cloud_mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(cloud_mask)


def mask_l7_clouds(image):
    # Landsat-7 Collection 2 also uses QA_PIXEL band with same bit interpretation
    qa = image.select("QA_PIXEL")
    cloud_mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(cloud_mask)


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/search_location", methods=["POST"])
def search_location():
    data = request.json
    location_name = data.get("location", "")

    if not location_name:
        return jsonify({"error": "Location name required"}), 400

    try:
        geolocator = Nominatim(user_agent="geo_pulse_app")
        location = geolocator.geocode(location_name, timeout=10)
        if location:
            return jsonify({"lat": location.latitude, "lon": location.longitude})
        else:
            return jsonify({"error": "Location not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload_aoi", methods=["POST"])
def upload_aoi():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(file_path)

        try:
            geojson_data = load_aoi_file(file_path, filename)
            if geojson_data:
                # Clean up uploaded file
                os.remove(file_path)

                return jsonify(
                    {
                        "success": True,
                        "geojson": geojson_data,
                        "filename": filename,
                        "original_name": os.path.splitext(filename)[0],
                    }
                )
            else:
                return jsonify({"error": "Failed to parse file"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Invalid file type"}), 400


@app.route("/api/download_aoi", methods=["POST"])
def download_aoi():
    data = request.json
    geojson_data = data.get("geojson")

    if not geojson_data:
        return jsonify({"error": "No GeoJSON data provided"}), 400

    # Save to temporary file
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".geojson", mode="w")
    json.dump(geojson_data, temp_file, indent=4)
    temp_file.close()

    return send_file(
        temp_file.name,
        as_attachment=True,
        download_name="aoi.geojson",
        mimetype="application/json",
    )


def remove_z_coordinates(geometry):
    """Recursively remove Z coordinates from geometry coordinates."""
    if "coordinates" in geometry:
        geometry["coordinates"] = _remove_z_recurse(geometry["coordinates"])
    return geometry


def _remove_z_recurse(coords):
    if not coords:
        return coords

    # Check if this is a coordinate point (list of numbers)
    if isinstance(coords[0], (int, float)):
        return coords[:2]  # Keep only x, y

    # Otherwise, it's a list of lists (or list of list of lists...)
    return [_remove_z_recurse(c) for c in coords]


@app.route("/api/task_status/<task_id>")
def task_status(task_id):
    if task_id in TASKS:
        return jsonify(TASKS[task_id])
    return jsonify({"error": "Task not found"}), 404


@app.route("/api/download/<task_id>")
def download_task_results(task_id):
    zip_path = os.path.join(DATA_DIR, f"results_{task_id}.zip")
    if os.path.exists(zip_path):
        return send_file(
            zip_path,
            as_attachment=True,
            download_name=f"satellite_data_{task_id[:8]}.zip"
        )
    return jsonify({"error": "Results not ready or task failed"}), 404


@app.route("/api/fetch_satellite_data", methods=["POST"])
def fetch_satellite_data_api():
    global EE_INITIALIZED

    if not EE_INITIALIZED:
        return jsonify(
            {
                "error": "Earth Engine is not initialized. Please configure Google Earth Engine authentication first."
            }
        ), 503

    data = request.json
    geojson_data = data.get("geojson")
    year = data.get("year")
    month = data.get("month", "all")
    limit = data.get("limit", "1")
    cloud_coverage = data.get("cloud_coverage", 20)
    satellite = data.get("satellite", "Sentinel-2")
    bands_selected = data.get("bands", [])
    aoi_name = data.get("aoi_name", "unknown_aoi")

    if not all([geojson_data, year]):
        return jsonify({"error": "Missing required parameters (geojson and year)"}), 400

    # Calculate start and end dates based on year and month
    try:
        if month == "all":
            start_date = f"{year}-01-01"
            end_date = f"{int(year) + 1}-01-01"
        else:
            month_num = int(month)
            start_date = f"{year}-{month_num:02d}-01"
            if month_num == 12:
                end_date = f"{int(year) + 1}-01-01"
            else:
                end_date = f"{year}-{month_num + 1:02d}-01"
    except Exception as e:
        return jsonify({"error": f"Invalid year or month: {str(e)}"}), 400

    try:
        # Parse geometry
        if geojson_data["type"] == "FeatureCollection":
            geom_dict = geojson_data["features"][0]["geometry"]
        else:
            geom_dict = geojson_data["geometry"]

        # Sanitize geometry (remove Z coordinates if present)
        geom_dict = remove_z_coordinates(geom_dict)

        geom = ee.Geometry(geom_dict)
        # Removed simplification to ensure accuracy for small AOIs

        # Create task
        task_id = str(uuid.uuid4())
        TASKS[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Initializing...",
            "details": "Starting download process",
        }

        # Start fetching in background thread
        thread = threading.Thread(
            target=fetch_satellite_images_wrapper,
            args=(
                geojson_data,
                start_date,
                end_date,
                cloud_coverage,
                satellite,
                task_id,
                bands_selected,
                aoi_name,
                limit,
                (month == "all")
            ),
        )
        thread.daemon = True
        thread.start()

        return jsonify(
            {
                "success": True,
                "task_id": task_id,
                "message": "Satellite data fetching started.",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def fetch_satellite_images_wrapper(
    geojson_data,
    start_date,
    end_date,
    cloud_coverage,
    satellite,
    task_id,
    bands_selected=None,
    aoi_name="unknown_aoi",
    limit="1",
    is_all_months_request=False
):
    try:
        features = geojson_data.get("features", [])
        total_features = len(features)
        
        # Determine bands once
        all_possible_bands, prefix = get_satellite_bands(satellite)
        if not all_possible_bands:
             TASKS[task_id]["status"] = "error"
             TASKS[task_id]["message"] = f"Unsupported satellite: {satellite}"
             TASKS[task_id]["progress"] = 100
             return

        target_bands = all_possible_bands
        if bands_selected:
            valid = [b for b in bands_selected if b in all_possible_bands]
            if valid:
                target_bands = valid
        
        TASKS[task_id]["message"] = "Preparing download batch..."
        
        task_root = os.path.join(DATA_DIR, f"task_{task_id}")
        os.makedirs(task_root, exist_ok=True)

        success_count = 0
        month_names_map = {
            "01": "January", "02": "February", "03": "March", "04": "April",
            "05": "May", "06": "June", "07": "July", "08": "August",
            "09": "September", "10": "October", "11": "November", "12": "December"
        }
        name_to_num = {v: k for k, v in month_names_map.items()}

        for index, feature in enumerate(features):
            props = feature.get("properties", {})
            f_year = props.get("custom_year")
            f_month = props.get("custom_month")
            plot_id = props.get("plot_id", aoi_name if total_features == 1 else f"plot_{index}")
            
            geom_dict = remove_z_coordinates(feature["geometry"])
            geom = ee.Geometry(geom_dict)
            
            # Determine processing mode for this feature
            if f_year and f_month:
                # Format month
                if f_month in name_to_num:
                    f_month_num = name_to_num[f_month]
                    f_month_name = f_month
                else:
                    try:
                        f_month_num = f"{int(f_month):02d}"
                        f_month_name = month_names_map.get(f_month_num, "January")
                    except:
                        f_month_num = "01"
                        f_month_name = "January"
                
                curr_start = f"{f_year}-{f_month_num}-01"
                if f_month_num == "12":
                    curr_end = f"{int(f_year)+1}-01-01"
                else:
                    curr_end = f"{f_year}-{int(f_month_num)+1:02d}-01"
                
                sub_folder = f"{f_month_name}_{f_year}_{plot_id}"
                TASKS[task_id]["message"] = f"Processing {index+1}/{total_features}: {sub_folder}"
                
                _fetch_single_roi(geom, curr_start, curr_end, cloud_coverage, satellite, target_bands, sub_folder, plot_id, prefix, limit, task_root)
                success_count += 1
            else:
                # Use UI-selected dates
                if is_all_months_request:
                    y_val = start_date.split("-")[0]
                    TASKS[task_id]["message"] = f"Processing {index+1}/{total_features} (All Months for {y_val})..."
                    
                    for m_idx in range(1, 13):
                        m_name = month_names_map[f"{m_idx:02d}"]
                        c_start = f"{y_val}-{m_idx:02d}-01"
                        if m_idx == 12:
                            c_end = f"{int(y_val)+1}-01-01"
                        else:
                            c_end = f"{y_val}-{m_idx+1:02d}-01"
                        
                        sub_folder = os.path.join(f"months_{y_val}_{plot_id}", m_name)
                        _fetch_single_roi(geom, c_start, c_end, cloud_coverage, satellite, target_bands, sub_folder, plot_id, prefix, limit, task_root)
                    success_count += 1
                else:
                    s_parts = start_date.split("-")
                    m_name = month_names_map.get(s_parts[1], "January")
                    y_val = s_parts[0]
                    
                    sub_folder = f"{m_name}_{y_val}_{plot_id}"
                    TASKS[task_id]["message"] = f"Processing {index+1}/{total_features}: {sub_folder}"
                    
                    _fetch_single_roi(geom, start_date, end_date, cloud_coverage, satellite, target_bands, sub_folder, plot_id, prefix, limit, task_root)
                    success_count += 1
            
            TASKS[task_id]["progress"] = int((index + 1) / total_features * 100)

        # Create ZIP
        if success_count > 0:
            TASKS[task_id]["message"] = "Creating results ZIP..."
            zip_filename = f"results_{task_id}.zip"
            zip_path = os.path.join(DATA_DIR, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(task_root):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, task_root)
                        zf.write(file_path, arcname)
            
            TASKS[task_id]["download_url"] = f"/api/download/{task_id}"
            TASKS[task_id]["message"] = f"Batch complete. {success_count} locations zipped."
        else:
            TASKS[task_id]["message"] = "No images were successfully downloaded."
            
        TASKS[task_id]["status"] = "success"
        TASKS[task_id]["progress"] = 100

    except Exception as e:
        print(f"Wrapper error: {e}")
        TASKS[task_id]["status"] = "error"
        TASKS[task_id]["message"] = f"Error: {str(e)}"
        TASKS[task_id]["progress"] = 100



def get_satellite_bands(satellite):
    if satellite == "Sentinel-2":
        return ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B11", "B12"], "S2"
    elif satellite == "Landsat-8":
        return ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"], "L8"
    elif satellite == "Landsat-7":
        return ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B7"], "L7"
    return [], None


def get_robust_collection(satellite, geom, start_date, end_date, cloud_coverage):
    """Try multiple collections and return the first non-empty one."""
    collections = []
    if satellite == "Sentinel-2":
        collections = [
            {"id": "COPERNICUS/S2_SR_HARMONIZED", "name": "Sentinel-2 SR Harmonized", "type": "SR"},
            {"id": "COPERNICUS/S2_SR", "name": "Sentinel-2 SR", "type": "SR"},
            {"id": "COPERNICUS/S2", "name": "Sentinel-2 TOA", "type": "TOA"}
        ]
    elif satellite == "Landsat-8":
        collections = [
            {"id": "LANDSAT/LC08/C02/T1_L2", "name": "Landsat 8 SR", "type": "SR"},
            {"id": "LANDSAT/LC08/C02/T1_TOA", "name": "Landsat 8 TOA", "type": "TOA"}
        ]
    elif satellite == "Landsat-7":
        collections = [
            {"id": "LANDSAT/LE07/C02/T1_L2", "name": "Landsat 7 SR", "type": "SR"},
            {"id": "LANDSAT/LE07/C02/T1_TOA", "name": "Landsat 7 TOA", "type": "TOA"}
        ]
    else:
        return None, None, False

    for coll_info in collections:
        col = (
            ee.ImageCollection(coll_info["id"])
            .filterBounds(geom)
            .filterDate(start_date, end_date)
        )
        
        if satellite == "Sentinel-2":
            col = col.filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", cloud_coverage))
        elif satellite == "Landsat-8" or satellite == "Landsat-7":
            col = col.filter(ee.Filter.lt("CLOUD_COVER", cloud_coverage))
        
        size = col.size().getInfo()
        if size > 0:
            return col, coll_info["name"], (coll_info["type"] == "TOA")
            
    return None, None, False


def _fetch_single_roi(geom, start_date, end_date, cloud_coverage, satellite, bands_selected, folder_name, aoi_name="unknown", prefix_override=None, limit="1", root_folder=None):
    try:
        col, coll_name, is_toa = get_robust_collection(satellite, geom, start_date, end_date, cloud_coverage)
        if not col:
            print(f"No images found for {folder_name} in any collection")
            return False

        print(f"✅ Found data in {coll_name} for {folder_name}")
        if satellite == "Sentinel-2":
            mask_func = mask_s2_clouds
            prefix = "S2"
        elif satellite == "Landsat-8":
            mask_func = mask_l8_clouds
            prefix = "L8"
        elif satellite == "Landsat-7":
            mask_func = mask_l7_clouds
            prefix = "L7"
        
        if prefix_override:
            prefix = prefix_override

        # Prepare bands
        all_possible_bands, _ = get_satellite_bands(satellite)
        if not bands_selected:
            bands_selected = all_possible_bands
        
        # TOA band mapping
        if is_toa and (satellite == "Landsat-8" or satellite == "Landsat-7"):
            bands_selected = [b.replace("SR_", "") if b.startswith("SR_") else b for b in bands_selected]

        col = col.map(mask_func)
        
        actual_count = col.size().getInfo()
        count = 1 if limit == "1" else actual_count
        
        if limit == "1":
            property_name = "CLOUDY_PIXEL_PERCENTAGE" if satellite == "Sentinel-2" else "CLOUD_COVER"
            col = col.sort(property_name)
        
        imgs = col.toList(count)
        months_saved = set()
        
        base_dir = root_folder if root_folder else DATA_DIR
        folder = os.path.join(base_dir, folder_name)
        os.makedirs(folder, exist_ok=True)
        
        for i in range(count):
            img = ee.Image(imgs.get(i))
            
            m_img = img.date().format("MMMM").getInfo()
            y_img = img.date().format("YYYY").getInfo()
            
            if limit == "1" and len(months_saved) >= 1: 
                break
            months_saved.add(m_img)

            img = img.clip(geom)
            region = geom.bounds().getInfo()["coordinates"]
            
            for band in bands_selected:
                filename = f"{m_img}_{y_img}_{aoi_name}_{band}.TIF"
                path = os.path.join(folder, filename)
                if os.path.exists(path):
                    continue

                scale = 10 if satellite == "Sentinel-2" and band in ["B2", "B3", "B4", "B8"] else 30
                try:
                    url = img.select(band).getDownloadURL({"scale": scale, "region": region, "format": "GEO_TIFF"})
                    r = requests.get(url)
                    if r.status_code == 200:
                        with open(path, "wb") as f:
                            f.write(r.content)
                except Exception as e:
                    print(f"Failed to download {band} for {folder_name}: {e}")

        return True

    except Exception as e:
        print(f"Error in _fetch_single_roi for {folder_name}: {e}")
        return False


def fetch_satellite_images(
    geom,
    start_date,
    end_date,
    cloud_coverage,
    satellite,
    task_id,
    bands_selected=None,
    aoi_name="unknown_aoi",
    limit="1",
    is_all_months=False
):
    try:
        task_root = os.path.join(DATA_DIR, f"task_{task_id}")
        os.makedirs(task_root, exist_ok=True)

        if is_all_months:
            TASKS[task_id]["message"] = "Starting month-by-month search..."
            TASKS[task_id]["progress"] = 5
            
            s_parts = start_date.split("-")
            y_val = s_parts[0]
            root_folder_name = f"months_{y_val}_{aoi_name}"
            
            month_names = {
                1: "January", 2: "February", 3: "March", 4: "April",
                5: "May", 6: "June", 7: "July", 8: "August",
                9: "September", 10: "October", 11: "November", 12: "December"
            }
            
            successful_months = 0
            for m_idx in range(1, 13):
                m_name = month_names[m_idx]
                TASKS[task_id]["message"] = f"Processing {m_name} {y_val}..."
                
                # Monthly date range
                curr_start = f"{y_val}-{m_idx:02d}-01"
                if m_idx == 12:
                    curr_end = f"{int(y_val)+1}-01-01"
                else:
                    curr_end = f"{y_val}-{m_idx+1:02d}-01"
                
                # Hierarchical folder
                m_path = os.path.join(root_folder_name, m_name)
                
                try:
                    success = _fetch_single_roi(
                        geom, curr_start, curr_end, cloud_coverage, 
                        satellite, bands_selected, m_path, 
                        aoi_name, None, limit="1", root_folder=task_root
                    )
                    if success:
                        successful_months += 1
                except Exception as e:
                    print(f"Failed {m_name}: {e}")
                
                TASKS[task_id]["progress"] = 5 + int((m_idx / 12) * 90)
            
            # Create ZIP for non-feature-split (fallback) mode
            if successful_months > 0:
                TASKS[task_id]["message"] = "Creating results ZIP..."
                zip_filename = f"results_{task_id}.zip"
                zip_path = os.path.join(DATA_DIR, zip_filename)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(task_root):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, task_root)
                            zf.write(file_path, arcname)
                TASKS[task_id]["download_url"] = f"/api/download/{task_id}"

            if successful_months == 0:
                TASKS[task_id]["status"] = "error"
                sat_hint = "from 2015" if satellite == "Sentinel-2" else "from 2013"
                TASKS[task_id]["message"] = (
                    f"No data found for any month in {y_val}. Tips: 1) {satellite} data is available only {sat_hint}. "
                    "2) Increase 'Maximum Cloud Coverage'. 3) Check region/dates."
                )
            else:
                TASKS[task_id]["status"] = "success"
                TASKS[task_id]["message"] = f"Completed. Found data for {successful_months}/12 months."
            
            TASKS[task_id]["progress"] = 100
            return

        # Single month mode (original logic)
        TASKS[task_id]["message"] = "Searching (Robust Mode)..."
        TASKS[task_id]["progress"] = 5
        
        col, coll_name, is_toa = get_robust_collection(satellite, geom, start_date, end_date, cloud_coverage)
        
        if not col:
            TASKS[task_id]["status"] = "error"
            sat_hint = "from 2015" if satellite == "Sentinel-2" else "from 2013"
            TASKS[task_id]["message"] = f"No images found. Tips: 1) {satellite} data is available {sat_hint}. 2) Increase 'Cloud Coverage'. 3) Check region."
            TASKS[task_id]["progress"] = 100
            return

        # Prepare bands and mask
        mask_func = mask_s2_clouds if satellite == "Sentinel-2" else mask_l8_clouds
        prefix = "S2" if satellite == "Sentinel-2" else "L8"
        all_b, _ = get_satellite_bands(satellite)
        bands = [b for b in bands_selected if b in all_b] if bands_selected else all_b
        if is_toa and satellite == "Landsat-8":
            bands = [b.replace("SR_", "") if b.startswith("SR_") else b for b in bands]

        col = col.map(mask_func)
        actual_count = col.size().getInfo()
        count = 1 if limit == "1" else actual_count
        if limit == "1":
            prop = "CLOUDY_PIXEL_PERCENTAGE" if satellite == "Sentinel-2" else "CLOUD_COVER"
            col = col.sort(prop)

        imgs = col.toList(count)
        
        # Determine root folder
        s_parts = start_date.split("-")
        y_val = s_parts[0]
        m_num = s_parts[1]
        m_name = {
            "01": "January", "02": "February", "03": "March", "04": "April",
            "05": "May", "06": "June", "07": "July", "08": "August",
            "09": "September", "10": "October", "11": "November", "12": "December"
        }.get(m_num, m_num)
        
        root_folder_name = f"{m_name}_{y_val}_{aoi_name}"
        folder = os.path.join(DATA_DIR, root_folder_name)
        os.makedirs(folder, exist_ok=True)
        
        months_saved = set()
        for i in range(count):
            img = ee.Image(imgs.get(i))
            y_img = img.date().format("YYYY").getInfo()
            m_img = img.date().format("MMMM").getInfo()
            
            if limit == "1" and len(months_saved) >= 1: break
            months_saved.add((y_img, m_img))

            img = img.clip(geom)
            region = geom.bounds().getInfo()["coordinates"]
            TASKS[task_id]["message"] = f"Downloading {m_img} {y_img}..."

            for band in bands:
                filename = f"{m_img}_{y_img}_{aoi_name}_{band}.TIF"
                # Use task_root for consistency
                if not os.path.exists(os.path.join(task_root, root_folder_name)):
                    os.makedirs(os.path.join(task_root, root_folder_name), exist_ok=True)
                path = os.path.join(task_root, root_folder_name, filename)
                
                if os.path.exists(path): continue
                
                scale = 10 if satellite == "Sentinel-2" and band in ["B2", "B3", "B4", "B8"] else 30
                try:
                    url = img.select(band).getDownloadURL({"scale": scale, "region": region, "format": "GEO_TIFF"})
                    r = requests.get(url)
                    if r.status_code == 200:
                        with open(path, "wb") as f: f.write(r.content)
                except: pass

        # Create ZIP for single-month ROI
        TASKS[task_id]["message"] = "Creating results ZIP..."
        zip_filename = f"results_{task_id}.zip"
        zip_path = os.path.join(DATA_DIR, zip_filename)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(task_root):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, task_root)
                    zf.write(file_path, arcname)
        TASKS[task_id]["download_url"] = f"/api/download/{task_id}"

        TASKS[task_id]["status"] = "success"
        TASKS[task_id]["message"] = "Download complete."
        TASKS[task_id]["progress"] = 100

    except Exception as e:
        print(f"Error fetching satellite data: {e}")
        TASKS[task_id]["status"] = "error"
        TASKS[task_id]["message"] = f"Error: {str(e)}"
        TASKS[task_id]["progress"] = 100


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
