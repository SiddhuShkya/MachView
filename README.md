# MachView

MachView is a powerful web application designed for processing and downloading satellite imagery using the Google Earth Engine API. It provides an intuitive interface for managing geospatial data, defining Areas of Interest (AOI), and fetching multispectral satellite bands.

## 🚀 Features

- **Google Earth Engine Integration**: Seamlessly connect to GEE for high-performance satellite data processing.
- **Multiple AOI Formats**: Support for uploading regional boundaries via GeoJSON, KML, KMZ, and Shapefile (zip).
- **Asynchronous Processing**: Long-running image retrieval tasks are handled in the background with real-time status updates.
- **Satellite Support**: Easy access to Sentinel-2, Landsat 8, and Landsat 7 imagery.
- **Persistent Configuration**: Redis-backed caching for Earth Engine credentials and application settings.
- **Dynamic Frontend**: A responsive dashboard built with modern JavaScript for AOI preview and task management.

## 🛠️ Tech Stack

- **Backend**: [Flask](https://flask.palletsprojects.com/) (Python)
- **Geospatial Processing**: [Google Earth Engine](https://earthengine.google.com/), [Fiona](https://fiona.readthedocs.io/), [Shapely](https://shapely.readthedocs.io/), [FastKML](https://fastkml.readthedocs.io/)
- **Caching/Queue**: [Redis](https://redis.io/)
- **Frontend**: Vanilla HTML5, CSS3, and JavaScript
- **Containerization**: [Docker](https://www.docker.com/), [Docker Compose](https://docs.docker.com/compose/)

## 📦 Getting Started

### Prerequisites

- A Google Earth Engine account with API access enabled.
- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) (Recommended).

### Method 1: Using Docker (Recommended)

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd MachView
   ```

2. **Start the application**:
   ```bash
   docker-compose up --build
   ```

3. **Access the web UI**:
   Open `http://localhost:5000` in your browser. Upon first launch, you will be prompted to provide your Earth Engine credentials.

### Method 2: Manual Setup (Local Development)

1. **Install dependencies**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```

2. **Run Redis**:
   Ensure a Redis server is running on `localhost:6379`.

3. **Start the Flask app**:
   ```bash
   python src/app.py
   ```

## 📂 Project Structure

- `src/`: Main application source code.
  - `app.py`: Flask backend server logic and GEE integration.
  - `index.html`: Main dashboard template.
  - `script.js`: Frontend logic for AOI handling and API communication.
  - `style.css`: UI styling.
- `data/`: Local storage for uploaded AOIs and processed results.
- `docker-compose.yml`: Configuration for the web and redis services.
- `Dockerfile`: Multi-stage build for the Flask application.
- `requirements.txt`: Python package dependencies.

## 📖 Usage

1. **Configure GEE**: On the first run, enter your Earth Engine project ID and credentials in the setup UI.
2. **Upload AOI**: Drag and drop or browse to select your GeoJSON, KML, or Shapefile.
3. **Select Satellite**: Choose between Sentinel-2, Landsat 8, or Landsat 7.
4. **Define Date Range**: Specify the temporal bounds for the imagery.
5. **Download**: Click "Fetch Satellite Data" to start the background task. You can monitor the progress on the dashboard and download the results once complete.
