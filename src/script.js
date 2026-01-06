/**
 * MachView Main JavaScript
    * Contains global logic used across multiple pages
        */

// Check Earth Engine status
async function checkEEStatus() {
    try {
        const response = await fetch('/api/ee_status');
        const data = await response.json();
        const statusAlert = document.getElementById('eeStatusAlert');
        const statusText = document.getElementById('eeStatusText');

        if (!statusAlert || !statusText) return;

        if (data.initialized) {
            statusAlert.className = 'alert alert-success mb-0 py-1 px-3';
            statusText.innerHTML = '<i class="fas fa-check-circle me-2"></i>Earth Engine is ready ✓';
            statusAlert.style.display = 'block';
        } else {
            statusAlert.className = 'alert alert-warning mb-0 py-1 px-3';
            if (data.status === 'not_configured') {
                statusText.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>Earth Engine is not configured.';
            } else {
                statusText.innerHTML = '<i class="fas fa-exclamation-circle me-2"></i>Earth Engine initialization failed.';
            }
            statusAlert.style.display = 'block';
        }
    } catch (error) {
        const statusAlert = document.getElementById('eeStatusAlert');
        const statusText = document.getElementById('eeStatusText');

        if (statusAlert && statusText) {
            statusAlert.className = 'alert alert-danger mb-0 py-1 px-3';
            statusText.innerHTML = '<i class="fas fa-exclamation-circle me-2"></i>Status check failed';
            statusAlert.style.display = 'block';
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function () {
    // Wait a bit to ensure DOM is fully ready
    setTimeout(() => {
        checkEEStatus();
    }, 100);
});

// --- fetch_satellite_data.js content ---

let map;
let aoiLayer = null;
let currentGeoJSON = null;
let currentTileLayer = null;
let sentinelChoices = null;
let landsatChoices = null;
let landsat7Choices = null;
let currentAOIName = null;

// Initialize map
function initMap() {
    const mapElement = document.getElementById('aoiMap');
    if (!mapElement) {
        console.error('Map container not found');
        return;
    }

    // Initialize map
    map = L.map('aoiMap', {
        zoomControl: true,
        attributionControl: true
    }).setView([28.7221, 80.6362], 7);

    // Add default tile layer
    currentTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);

    // Invalidate size after a short delay to ensure proper rendering
    setTimeout(() => {
        map.invalidateSize();
    }, 100);

    console.log('Map initialized successfully');
}

// Change map type
function changeMapType(type) {
    if (!map) {
        console.error('Map not initialized');
        return;
    }

    const mapType = type || 'Default';

    // Remove current tile layer
    if (currentTileLayer) {
        map.removeLayer(currentTileLayer);
    }

    // Add new tile layer based on selection
    if (mapType === 'Satellite') {
        currentTileLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Esri World Imagery',
            maxZoom: 19
        }).addTo(map);
    } else {
        currentTileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(map);
    }

    // Re-add AOI layer if it exists
    if (aoiLayer) {
        map.addLayer(aoiLayer);
        // Re-fit bounds to AOI
        if (aoiLayer.getBounds().isValid()) {
            map.fitBounds(aoiLayer.getBounds(), {
                padding: [50, 50],
                maxZoom: 15
            });
        }
    }

    // Invalidate map size
    setTimeout(() => {
        map.invalidateSize();
    }, 100);

    console.log('Map type changed to:', mapType);
}

// Upload AOI file
async function uploadAOI() {
    const fileInput = document.getElementById('aoiUpload');
    const file = fileInput.files[0];
    const uploadBtn = document.getElementById('uploadBtn');

    if (!file) {
        showAlert('Please select a file', 'warning');
        updateStatus('Please select an AOI file to upload.', 'info');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    // Show loading state
    const originalBtnText = uploadBtn.innerHTML;
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Uploading...';
    updateStatus('Uploading AOI file...', 'info');
    updateStatusBadge('Uploading');

    try {
        const response = await fetch('/api/upload_aoi', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            currentGeoJSON = data.geojson;
            currentAOIName = data.original_name;

            // Ensure map is initialized before displaying
            if (!map) {
                initMap();
            }

            // Show config card first
            document.getElementById('configCard').style.display = 'block';

            // Wait a bit for map to be ready and card to be visible, then display AOI
            setTimeout(() => {
                // Invalidate map size in case container was hidden
                if (map) {
                    map.invalidateSize();
                }
                displayAOIOnMap(currentGeoJSON);
            }, 300);
            updateStatus('AOI uploaded successfully! You can now configure the satellite data fetch parameters.', 'success');
            updateStatusBadge('Ready');
            showAlert('AOI uploaded successfully!', 'success');
        } else {
            updateStatus(data.error || 'Failed to upload AOI', 'danger');
            updateStatusBadge('Error');
            showAlert(data.error || 'Failed to upload AOI', 'danger');
        }
    } catch (error) {
        updateStatus('Error uploading file: ' + error.message, 'danger');
        updateStatusBadge('Error');
        showAlert('Error uploading file: ' + error.message, 'danger');
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerHTML = originalBtnText;
    }
}

// Display AOI on map
function displayAOIOnMap(geojson) {
    if (!map) {
        console.error('Map not initialized');
        return;
    }

    try {
        // Remove existing AOI layer
        if (aoiLayer) {
            map.removeLayer(aoiLayer);
            aoiLayer = null;
        }

        // Validate geojson
        if (!geojson || !geojson.features || geojson.features.length === 0) {
            console.error('Invalid GeoJSON data');
            showAlert('Invalid GeoJSON data. Please check your file.', 'danger');
            return;
        }

        // Add new AOI layer
        aoiLayer = L.geoJSON(geojson, {
            style: {
                color: '#FF2D2D',
                weight: 3,
                opacity: 0.7,
                fillColor: '#FF2D2D',
                fillOpacity: 0.2
            },
            onEachFeature: function (feature, layer) {
                if (feature.properties) {
                    let popupContent = '<div class="text-dark"><strong>AOI Feature</strong><br>';
                    for (let key in feature.properties) {
                        if (feature.properties[key]) {
                            popupContent += `<strong>${key}:</strong> ${feature.properties[key]}<br>`;
                        }
                    }
                    popupContent += '</div>';
                    layer.bindPopup(popupContent);
                }
            }
        }).addTo(map);

        // Fit map to AOI bounds with padding
        if (aoiLayer.getBounds().isValid()) {
            map.fitBounds(aoiLayer.getBounds(), {
                padding: [50, 50],
                maxZoom: 15
            });
        } else {
            // If bounds are invalid, try to get center from first feature
            const firstFeature = geojson.features[0];
            if (firstFeature && firstFeature.geometry) {
                const coords = firstFeature.geometry.coordinates;
                if (coords && coords.length > 0) {
                    // Handle different geometry types
                    let center;
                    if (firstFeature.geometry.type === 'Point') {
                        center = [coords[1], coords[0]];
                        map.setView(center, 12);
                    } else if (firstFeature.geometry.type === 'Polygon') {
                        const firstRing = coords[0];
                        const lats = firstRing.map(c => c[1]);
                        const lons = firstRing.map(c => c[0]);
                        center = [
                            (Math.max(...lats) + Math.min(...lats)) / 2,
                            (Math.max(...lons) + Math.min(...lons)) / 2
                        ];
                        map.setView(center, 12);
                    }
                }
            }
        }

        // Invalidate map size to ensure proper rendering (multiple times to be sure)
        setTimeout(() => {
            map.invalidateSize();
        }, 100);

        setTimeout(() => {
            map.invalidateSize();
            // Fit bounds again after size is corrected
            if (aoiLayer && aoiLayer.getBounds().isValid()) {
                map.fitBounds(aoiLayer.getBounds(), {
                    padding: [50, 50],
                    maxZoom: 15
                });
            }
        }, 300);

        console.log('AOI displayed on map successfully');
    } catch (error) {
        console.error('Error displaying AOI on map:', error);
        showAlert('Error displaying AOI on map: ' + error.message, 'danger');
    }
}

// Fetch satellite data
async function fetchSatelliteData(satellite) {
    if (!currentGeoJSON) {
        showAlert('Please upload an AOI file first', 'warning');
        return;
    }

    let year, month, limit, cloudCoverage, bandsSelect, fetchBtnId;

    if (satellite === 'Sentinel-2') {
        year = document.getElementById('yearSentinel').value;
        month = document.getElementById('monthSentinel').value;
        limit = "1";
        cloudCoverage = document.getElementById('cloudCoverageSentinel').value;
        bandsSelect = document.getElementById('bandsSentinel');
        fetchBtnId = 'fetchBtnSentinel';
    } else if (satellite === 'Landsat-8') {
        year = document.getElementById('yearLandsat').value;
        month = document.getElementById('monthLandsat').value;
        limit = "1";
        cloudCoverage = document.getElementById('cloudCoverageLandsat').value;
        bandsSelect = document.getElementById('bandsLandsat');
        fetchBtnId = 'fetchBtnLandsat';
    } else if (satellite === 'Landsat-7') {
        year = document.getElementById('yearLandsat7').value;
        month = document.getElementById('monthLandsat7').value;
        limit = "1";
        cloudCoverage = document.getElementById('cloudCoverageLandsat7').value;
        bandsSelect = document.getElementById('bandsLandsat7');
        fetchBtnId = 'fetchBtnLandsat7';
    } else {
        console.error('Unknown satellite:', satellite);
        return;
    }

    const fetchBtn = document.getElementById(fetchBtnId);

    // Get selected bands
    let selectedBands = [];
    if (satellite === 'Sentinel-2' && sentinelChoices) {
        selectedBands = sentinelChoices.getValue(true);
    } else if (satellite === 'Landsat-8' && landsatChoices) {
        selectedBands = landsatChoices.getValue(true);
    } else if (satellite === 'Landsat-7' && landsat7Choices) {
        selectedBands = landsat7Choices.getValue(true);
    } else {
        // Fallback to standard select if Choices not initialized
        selectedBands = Array.from(bandsSelect.selectedOptions).map(option => option.value);
    }

    // Check for batch mode (custom dates in features)
    let isBatchMode = false;
    if (currentGeoJSON && currentGeoJSON.features && currentGeoJSON.features.length > 0) {
        if (currentGeoJSON.features[0].properties && currentGeoJSON.features[0].properties.custom_year) {
            isBatchMode = true;
            console.log("Batch mode detected");
        }
    }

    if (!isBatchMode) {
        if (!year) {
            showAlert('Please select a year', 'warning');
            return;
        }
    }

    if (selectedBands.length === 0) {
        showAlert('Please select at least one band', 'warning');
        return;
    }

    // Show loading state
    const originalBtnText = fetchBtn.innerHTML;
    fetchBtn.disabled = true;
    fetchBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Fetching...';
    updateStatus(`Fetching ${satellite} data... This may take several minutes. Check the data/satellite_data folder for results.`, 'info');
    updateStatusBadge('Processing');

    // Show progress container
    const progressContainer = document.getElementById('progressContainer');
    if (progressContainer) {
        progressContainer.style.display = 'block';
        simulateProgress();
    }

    try {
        const response = await fetch('/api/fetch_satellite_data', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                geojson: currentGeoJSON,
                year: year,
                month: month,
                limit: limit,
                cloud_coverage: parseInt(cloudCoverage),
                satellite: satellite,
                bands: selectedBands,
                aoi_name: currentAOIName
            })
        });

        const data = await response.json();

        if (response.ok) {
            updateStatus(data.message || 'Satellite data fetching started successfully!', 'info');
            updateStatusBadge('Processing');

            // Start polling for progress
            if (data.task_id) {
                pollProgress(data.task_id, fetchBtnId);
            } else {
                // Fallback if no task_id (shouldn't happen with new backend)
                simulateProgress();
            }
        } else {
            updateStatus(data.error || 'Failed to fetch satellite data', 'danger');
            updateStatusBadge('Error');
            showAlert(data.error || 'Failed to fetch satellite data', 'danger');
            fetchBtn.disabled = false;
            fetchBtn.innerHTML = originalBtnText;
            if (progressContainer) progressContainer.style.display = 'none';
        }
    } catch (error) {
        updateStatus('Error fetching satellite data: ' + error.message, 'danger');
        updateStatusBadge('Error');
        showAlert('Error fetching satellite data: ' + error.message, 'danger');
        fetchBtn.disabled = false;
        fetchBtn.innerHTML = originalBtnText;
        if (progressContainer) progressContainer.style.display = 'none';
    }
}

// Poll progress from backend
function pollProgress(taskId, fetchBtnId) {
    const progressText = document.getElementById('progressText');
    const fetchBtn = document.getElementById(fetchBtnId || 'fetchBtn');

    const interval = setInterval(async () => {
        try {
            const response = await fetch(`/api/task_status/${taskId}`);
            const data = await response.json();

            if (response.ok) {
                // Update progress text
                if (progressText) progressText.textContent = `${data.message} (${data.progress}%)`;

                // Check status
                if (data.status === 'success') {
                    clearInterval(interval);
                    updateStatus(data.message, 'success');
                    updateStatusBadge('Success');
                    showAlert('Satellite data fetching completed successfully!', 'success');

                    // Show download button if available
                    if (data.download_url) {
                        const downloadContainer = document.getElementById('downloadContainer');
                        if (downloadContainer) {
                            downloadContainer.innerHTML = `
                                <a href="${data.download_url}" class="btn btn-outline-success w-100 bounce-in shadow-sm">
                                    <i class="fas fa-file-archive me-2"></i>Download Results ZIP
                                </a>`;
                            downloadContainer.style.display = 'block';
                        }
                    }

                    if (fetchBtn) {
                        fetchBtn.disabled = false;
                        const satName = fetchBtnId.includes('Sentinel') ? 'Sentinel-2' :
                            fetchBtnId.includes('Landsat7') ? 'Landsat-7' : 'Landsat-8';
                        fetchBtn.innerHTML = `<i class="fas fa-rocket me-2"></i>Fetch ${satName} Data`;
                    }
                } else if (data.status === 'error') {
                    clearInterval(interval);
                    updateStatus(data.message, 'danger');
                    updateStatusBadge('Error');
                    showAlert(data.message, 'danger');

                    if (fetchBtn) {
                        fetchBtn.disabled = false;
                        const satName = fetchBtnId.includes('Sentinel') ? 'Sentinel-2' :
                            fetchBtnId.includes('Landsat7') ? 'Landsat-7' : 'Landsat-8';
                        fetchBtn.innerHTML = `<i class="fas fa-rocket me-2"></i>Fetch ${satName} Data`;
                    }
                }
            }
        } catch (error) {
            console.error('Error polling progress:', error);
        }
    }, 1000);
}

// Simulate progress (fallback)
function simulateProgress() {
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    let progress = 0;

    const interval = setInterval(() => {
        progress += Math.random() * 10;
        if (progress > 90) progress = 90; // Don't go to 100% since it's background

        if (progressText) {
            progressText.textContent = `Processing... ${Math.floor(progress)}%`;
        }

        if (progress >= 90) {
            clearInterval(interval);
            if (progressText) {
                progressText.textContent = 'Processing in background. Check data/satellite_data folder for results.';
            }
        }
    }, 500);
}

// Update status message
function updateStatus(message, type) {
    const statusDiv = document.getElementById('statusMessage');
    if (!statusDiv) return;

    const icons = {
        'info': '<i class="fas fa-info-circle me-2"></i>',
        'success': '<i class="fas fa-check-circle me-2"></i>',
        'warning': '<i class="fas fa-exclamation-triangle me-2"></i>',
        'danger': '<i class="fas fa-exclamation-circle me-2"></i>'
    };

    statusDiv.className = `alert alert-${type}`;
    statusDiv.innerHTML = (icons[type] || '') + message;
}

// Update status badge
function updateStatusBadge(status) {
    const badge = document.getElementById('statusBadge');
    if (!badge) return;

    const badgeClasses = {
        'Ready': 'bg-info',
        'Uploading': 'bg-warning',
        'Processing': 'bg-primary',
        'Success': 'bg-success',
        'Error': 'bg-danger'
    };

    badge.textContent = status;
    badge.className = `badge ${badgeClasses[status] || 'bg-secondary'}`;
}

// Show alert
function showAlert(message, type) {
    const alertBox = document.getElementById('alertBox');
    const alertText = document.getElementById('alertText');
    if (!alertBox || !alertText) return;

    const icons = {
        'info': '<i class="fas fa-info-circle me-2"></i>',
        'success': '<i class="fas fa-check-circle me-2"></i>',
        'warning': '<i class="fas fa-exclamation-triangle me-2"></i>',
        'danger': '<i class="fas fa-exclamation-circle me-2"></i>'
    };

    alertBox.className = `alert alert-${type}`;
    alertText.innerHTML = (icons[type] || '') + message;
    alertBox.style.display = 'block';

    // Scroll to alert
    alertBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    setTimeout(() => {
        alertBox.style.display = 'none';
    }, 5000);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function () {
    // Wait a bit to ensure DOM is fully ready
    setTimeout(() => {
        initMap();

        // Initialize Choices.js
        if (document.getElementById('bandsSentinel')) {
            sentinelChoices = new Choices('#bandsSentinel', {
                removeItemButton: true,
                placeholder: true,
                placeholderValue: 'Select bands',
                searchPlaceholderValue: 'Search bands...',
                itemSelectText: '',
            });
        }

        if (document.getElementById('bandsLandsat')) {
            landsatChoices = new Choices('#bandsLandsat', {
                removeItemButton: true,
                placeholder: true,
                placeholderValue: 'Select bands',
                searchPlaceholderValue: 'Search bands...',
                itemSelectText: '',
            });
        }

        if (document.getElementById('bandsLandsat7')) {
            landsat7Choices = new Choices('#bandsLandsat7', {
                removeItemButton: true,
                placeholder: true,
                placeholderValue: 'Select bands',
                searchPlaceholderValue: 'Search bands...',
                itemSelectText: '',
            });
        }
    }, 100);
});

// Also initialize map when window loads (in case DOMContentLoaded already fired)
window.addEventListener('load', function () {
    if (!map) {
        setTimeout(() => {
            initMap();
        }, 100);
    }
});
