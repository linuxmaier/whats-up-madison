import { useState, useMemo } from 'react'
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import MarkerClusterGroup from 'react-leaflet-cluster'
import L from 'leaflet'
import iconRetina from 'leaflet/dist/images/marker-icon-2x.png'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'
import { formatTimeRange } from '../lib/eventTime'
import EventModal from './EventModal'

// Bundlers strip the default marker icon paths; restore them once on import.
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: iconRetina,
  iconUrl,
  shadowUrl,
})

const MADISON_CENTER = [43.0731, -89.4012]
const DEFAULT_ZOOM = 13

function groupByCoord(events) {
  const groups = new Map()
  for (const e of events) {
    if (e.latitude == null || e.longitude == null) continue
    const key = `${e.latitude.toFixed(5)},${e.longitude.toFixed(5)}`
    if (!groups.has(key)) {
      groups.set(key, { key, lat: e.latitude, lng: e.longitude, events: [] })
    }
    groups.get(key).events.push(e)
  }
  return [...groups.values()]
}

function makeBadgeIcon(count) {
  if (count <= 1) return new L.Icon.Default()
  return L.divIcon({
    className: 'wum-multi-pin',
    html: `
      <div style="position: relative;">
        <img src="${iconUrl}" style="width: 25px; height: 41px; display: block;" />
        <div style="
          position: absolute;
          top: -4px;
          right: -8px;
          background: #2563eb;
          color: white;
          border-radius: 9999px;
          font-size: 11px;
          font-weight: 600;
          min-width: 18px;
          height: 18px;
          padding: 0 4px;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 2px solid white;
          box-shadow: 0 1px 2px rgba(0,0,0,0.3);
        ">${count}</div>
      </div>
    `,
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
  })
}

export default function MapView({ events, stickyTop = 0 }) {
  const [activeEvent, setActiveEvent] = useState(null)
  const [showNoLoc, setShowNoLoc] = useState(false)

  const groups = useMemo(() => groupByCoord(events), [events])
  const noLocEvents = useMemo(
    () => events.filter(e => e.latitude == null || e.longitude == null),
    [events]
  )

  const mapHeight = `calc(100vh - ${stickyTop + 32}px)`

  return (
    <div className="mt-4">
      <div
        style={{ height: mapHeight, minHeight: '400px' }}
        className="rounded-lg overflow-hidden border border-gray-200 shadow-sm"
      >
        <MapContainer
          center={MADISON_CENTER}
          zoom={DEFAULT_ZOOM}
          scrollWheelZoom
          style={{ height: '100%', width: '100%' }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MarkerClusterGroup chunkedLoading>
            {groups.map(group => (
              <Marker
                key={group.key}
                position={[group.lat, group.lng]}
                icon={makeBadgeIcon(group.events.length)}
              >
                <Popup>
                  <PinPopup group={group} onPick={setActiveEvent} />
                </Popup>
              </Marker>
            ))}
          </MarkerClusterGroup>
        </MapContainer>
      </div>

      {noLocEvents.length > 0 && (
        <div className="mt-3 bg-amber-50 border border-amber-200 rounded px-3 py-2 text-sm text-amber-900">
          <button onClick={() => setShowNoLoc(v => !v)} className="font-medium cursor-pointer">
            {noLocEvents.length} event{noLocEvents.length === 1 ? '' : 's'} without a location {showNoLoc ? '▲' : '▼'}
          </button>
          {showNoLoc && (
            <ul className="mt-2 space-y-1">
              {noLocEvents.map(e => (
                <li key={e.id}>
                  <button
                    className="text-left hover:underline cursor-pointer"
                    onClick={() => setActiveEvent(e)}
                  >
                    {e.all_day ? 'All day' : formatTimeRange(e.start_at, e.end_at)} — {e.title}
                    {e.venue_name ? <span className="text-amber-700"> · {e.venue_name}</span> : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {activeEvent && <EventModal event={activeEvent} onClose={() => setActiveEvent(null)} />}
    </div>
  )
}

function PinPopup({ group, onPick }) {
  if (group.events.length === 1) {
    const e = group.events[0]
    return (
      <div style={{ minWidth: '200px' }}>
        <div style={{ fontSize: '11px', color: '#9ca3af', marginBottom: '2px' }}>
          {e.all_day ? 'All day' : formatTimeRange(e.start_at, e.end_at)}
        </div>
        <div style={{ fontSize: '14px', fontWeight: 600, color: '#111827', lineHeight: '1.3' }}>
          {e.title}
        </div>
        {e.venue_name && (
          <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>{e.venue_name}</div>
        )}
        <button
          onClick={() => onPick(e)}
          style={{
            marginTop: '8px',
            padding: '4px 10px',
            background: '#2563eb',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            fontSize: '12px',
            cursor: 'pointer',
          }}
        >
          View details
        </button>
      </div>
    )
  }

  return (
    <div style={{ minWidth: '220px', maxWidth: '280px' }}>
      <div style={{ fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '6px' }}>
        {group.events.length} events here
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, maxHeight: '240px', overflowY: 'auto' }}>
        {group.events.map(e => (
          <li key={e.id} style={{ marginBottom: '4px' }}>
            <button
              onClick={() => onPick(e)}
              style={{
                width: '100%',
                textAlign: 'left',
                padding: '4px 6px',
                background: 'transparent',
                border: '1px solid transparent',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '12px',
                lineHeight: '1.3',
              }}
              onMouseEnter={ev => { ev.currentTarget.style.background = '#f3f4f6' }}
              onMouseLeave={ev => { ev.currentTarget.style.background = 'transparent' }}
            >
              <span style={{ color: '#9ca3af' }}>
                {e.all_day ? 'All day' : formatTimeRange(e.start_at, e.end_at)}
              </span>
              <span style={{ color: '#111827', marginLeft: '6px', fontWeight: 500 }}>{e.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
