"use strict";

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[character]));

async function readJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Something went wrong. Please try again.");
  return body;
}

function setupMap() {
  const mapElement = document.querySelector("#parking-map");
  if (!mapElement) return;

  const fallback = document.querySelector("#map-fallback");
  const resultsElement = document.querySelector("#location-results");
  const detailElement = document.querySelector("#location-detail");
  const searchInput = document.querySelector("#location-search");
  const accessibilityInput = document.querySelector("#accessible-filter");
  const reportLocation = document.querySelector("#report-location");
  let map;
  let markers;
  let locations = [];
  let selectedLocationId = null;

  if (window.L) {
    map = window.L.map("parking-map", { scrollWheelZoom: false }).setView([29.36, 47.99], 12);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);
    markers = window.L.layerGroup().addTo(map);
  } else {
    fallback.hidden = false;
  }

  const markerIcon = (location) => window.L.divIcon({
    className: "",
    html: `<span class="map-marker ${location.color}"><b>${location.available_spots}</b></span>`,
    iconSize: [38, 38],
    iconAnchor: [19, 19]
  });

  function selectLocation(location, panMap = true) {
    selectedLocationId = location.id;
    if (reportLocation) reportLocation.value = String(location.id);
    const directionUrl = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${location.latitude},${location.longitude}`)}`;
    detailElement.innerHTML = `
      <p class="eyebrow">${escapeHtml(location.city)}</p>
      <h2>${escapeHtml(location.name)}</h2>
      <p>${escapeHtml(location.address)}</p>
      <div class="detail-availability"><span class="availability-dot ${location.color}"></span><strong>${location.available_spots} of ${location.total_spots} spaces available</strong></div>
      <p class="muted">${escapeHtml(location.description)}</p>
      ${location.is_accessible ? '<p class="accessible-note">Accessible parking is available here.</p>' : ''}
      <div class="detail-actions"><a class="button primary" target="_blank" rel="noopener" href="${directionUrl}">Get directions</a><button id="favorite-button" class="button secondary" type="button">${location.is_favorite ? "Remove favourite" : "Save favourite"}</button></div>`;
    const favoriteButton = document.querySelector("#favorite-button");
    if (favoriteButton) {
      favoriteButton.addEventListener("click", async () => {
        favoriteButton.disabled = true;
        try {
          const method = location.is_favorite ? "DELETE" : "POST";
          const data = await readJson(await fetch(`/api/favorites/${location.id}`, { method }));
          location.is_favorite = data.is_favorite;
          selectLocation(location, false);
          renderResults();
        } catch (error) {
          detailElement.insertAdjacentHTML("beforeend", `<p class="form-feedback error-text">${escapeHtml(error.message)}</p>`);
        } finally {
          favoriteButton.disabled = false;
        }
      });
    }
    if (map && panMap) map.setView([location.latitude, location.longitude], 15);
  }

  function renderResults() {
    if (!locations.length) {
      resultsElement.innerHTML = '<p class="empty-state">No parking locations match that search.</p>';
      return;
    }
    resultsElement.innerHTML = locations.map((location) => `
      <button class="map-result ${selectedLocationId === location.id ? "selected" : ""}" type="button" data-location-id="${location.id}">
        <span class="availability-dot ${location.color}"></span><span><strong>${escapeHtml(location.name)}</strong><small>${location.available_spots}/${location.total_spots} available · ${escapeHtml(location.city)}</small></span>${location.is_favorite ? '<span aria-label="Saved location">★</span>' : ''}
      </button>`).join("");
    resultsElement.querySelectorAll("[data-location-id]").forEach((button) => {
      button.addEventListener("click", () => {
        const location = locations.find((item) => item.id === Number(button.dataset.locationId));
        if (location) selectLocation(location);
      });
    });
  }

  function renderMarkers(fitBounds) {
    if (!map) return;
    markers.clearLayers();
    const bounds = [];
    locations.forEach((location) => {
      const marker = window.L.marker([location.latitude, location.longitude], { icon: markerIcon(location) })
        .bindTooltip(`${location.name}: ${location.available_spots}/${location.total_spots} available`)
        .on("click", () => selectLocation(location, false));
      marker.addTo(markers);
      bounds.push([location.latitude, location.longitude]);
    });
    if (fitBounds && bounds.length) map.fitBounds(bounds, { padding: [35, 35], maxZoom: 13 });
  }

  async function loadLocations(fitBounds = false) {
    const params = new URLSearchParams();
    if (searchInput.value.trim()) params.set("query", searchInput.value.trim());
    if (accessibilityInput.checked) params.set("accessible_only", "true");
    try {
      const data = await readJson(await fetch(`/api/parking-locations?${params.toString()}`));
      locations = data.locations;
      renderResults();
      renderMarkers(fitBounds);
      if (selectedLocationId) {
        const selected = locations.find((location) => location.id === selectedLocationId);
        if (selected) selectLocation(selected, false);
      }
    } catch (error) {
      resultsElement.innerHTML = `<p class="empty-state">${escapeHtml(error.message)}</p>`;
    }
  }

  let searchTimer;
  searchInput.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => loadLocations(true), 250);
  });
  accessibilityInput.addEventListener("change", () => loadLocations(true));
  loadLocations(true);
  window.setInterval(() => loadLocations(false), 10000);

  const reportForm = document.querySelector("#report-form");
  if (reportForm) {
    reportForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const feedback = document.querySelector("#report-feedback");
      const submitButton = reportForm.querySelector("button[type=submit]");
      submitButton.disabled = true;
      feedback.textContent = "Submitting…";
      try {
        const data = await readJson(await fetch("/api/reports", { method: "POST", body: new FormData(reportForm) }));
        feedback.className = "form-feedback success-text";
        feedback.textContent = data.message;
        reportForm.reset();
        if (selectedLocationId) reportLocation.value = String(selectedLocationId);
      } catch (error) {
        feedback.className = "form-feedback error-text";
        feedback.textContent = error.message;
      } finally {
        submitButton.disabled = false;
      }
    });
  }
}

function setupPrediction() {
  const form = document.querySelector("#prediction-form");
  if (!form) return;
  const result = document.querySelector("#prediction-result");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    result.innerHTML = '<p class="muted">Calculating estimate…</p>';
    try {
      const params = new URLSearchParams({ location_id: formData.get("location_id"), hour: formData.get("hour") });
      const data = await readJson(await fetch(`/api/analytics/prediction?${params.toString()}`));
      const className = data.band.toLowerCase();
      result.innerHTML = `<p class="eyebrow">Availability likelihood</p><div class="prediction-number ${className}">${data.chance}%</div><h2>${escapeHtml(data.band)} chance of finding a space</h2><p>For the selected hour, based on ${escapeHtml(data.basis)}.</p><p class="muted">Always check the live map before travelling; this feature does not reserve a space.</p>`;
    } catch (error) {
      result.innerHTML = `<p class="form-feedback error-text">${escapeHtml(error.message)}</p>`;
    } finally {
      button.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupMap();
  setupPrediction();
});
