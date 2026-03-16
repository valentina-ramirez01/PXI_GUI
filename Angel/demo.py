# rt_fgen_dash.py
# Reminder for future-me: this file configures a Dash UI to control NI-FGEN hardware,
# synthesize previews, optionally stream NI-SCOPE data, and allow quick recording.
import os
import threading
from enum import Enum
from datetime import datetime
from pathlib import Path

import dash
from dash import dcc, html, ctx
from dash.dependencies import Input, Output, State, ALL
from dash_iconify import DashIconify
import plotly.graph_objs as go
import numpy as np
import nifgen

# =================== CONFIG ===================
# Hard caps + defaults for the hardware UI. Adjust only if HW limits change.
MAX_VPP = 12.0                      # PXIe-5413 max amplitude in Vpp
RESOURCE_NAME = "Func_Gen"          # NI-FGEN alias or VISA name

# Optional measurement with NI-SCOPE
USE_SCOPE = os.getenv("USE_SCOPE", "0") == "1"
SCOPE_RESOURCE_NAME = "Oscilloscope"
SCOPE_CHANNELS = "0"
SCOPE_SAMPLERATE = 100e6
SCOPE_CHUNK_SAMPLES = 2_000         # samples fetched per UI tick

# Streaming UI parameters
REFRESH_MS = 50                     # UI tick period
DEFAULT_WINDOW_POINTS = 100_000     # fallback rolling window length
PREVIEW_FS = 1e6                    # preview sample rate when simulating
PREVIEW_CHUNK = 2_000               # simulated samples per tick
AUTO_CYCLES = 3                     # show 3 periods when autoscale is enabled
AUTOSCALE_SAMPLES_PER_PERIOD = 400  # resolution for autoscale preview
# ==============================================

class MyWaveform(Enum):
    SINE = nifgen.Waveform.SINE
    SQUARE = nifgen.Waveform.SQUARE
    TRIANGLE = nifgen.Waveform.TRIANGLE
    NOISE = nifgen.Waveform.NOISE
    RAMP_UP = nifgen.Waveform.RAMP_UP
    RAMP_DOWN = nifgen.Waveform.RAMP_DOWN

WAVEFORM_NAMES = [wf.name for wf in MyWaveform]

FREQ_UNIT_OPTIONS = ["HZ", "KHZ", "MHZ"]
FREQ_UNIT_LABELS = {"HZ": "Hz", "KHZ": "kHz", "MHZ": "MHz"}
UNIT_FACTORS = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6}

# ------------ NI-FGEN session ------------
fgen_lock = threading.Lock()
fgen = None

def configure_fgen(waveform_enum, freq_hz, amp_vpp):
    """Create or reconfigure the NI-FGEN session."""
    global fgen
    with fgen_lock:
        if fgen is None:
            fgen = nifgen.Session(RESOURCE_NAME)
        fgen.abort()
        fgen.configure_standard_waveform(
            waveform=waveform_enum.value,
            amplitude=amp_vpp,       # Vpp
            frequency=freq_hz,
            dc_offset=0.0,
            start_phase=0.0,
        )
        fgen.output_mode = nifgen.OutputMode.FUNC
        fgen.initiate()

# ------------ NI-SCOPE session (optional) ------------
scope_lock = threading.Lock()
scope = None
scope_dt = None  # seconds/sample

recording_lock = threading.Lock()
recording_buffer = {"x": [], "y": []}

DOWNLOAD_DIR = Path(os.environ.get("USERPROFILE", Path.cwd())) / "Downloads"

def ensure_scope():
    """Open and configure a persistent NI-SCOPE session."""
    global scope, scope_dt
    if not USE_SCOPE:
        return
    with scope_lock:
        if scope is not None:
            return
        import niscope
        scope = niscope.Session(SCOPE_RESOURCE_NAME)
        ch = scope.channels[SCOPE_CHANNELS]
        ch.configure_vertical(
            range=MAX_VPP, offset=0.0,
            coupling=niscope.VerticalCoupling.DC,
            probe_attenuation=1.0, enabled=True
        )
        scope.configure_horizontal_timing(
            min_sample_rate=SCOPE_SAMPLERATE,
            min_num_pts=SCOPE_CHUNK_SAMPLES,
            ref_position=0.0, num_records=1, enforce_realtime=True
        )
        scope.configure_trigger_immediate()
        # Prime once to get x_increment
        with scope.initiate():
            wf = ch.fetch(SCOPE_CHUNK_SAMPLES, timeout=1.0)[0]
        scope_dt = wf.x_increment

def fetch_scope_chunk():
    """Return one chunk (t_rel, y) using the persistent scope session."""
    import niscope  # local import to avoid requirement when not used
    with scope_lock:
        ch = scope.channels[SCOPE_CHANNELS]
        scope.configure_trigger_immediate()
        with scope.initiate():
            wf = ch.fetch(SCOPE_CHUNK_SAMPLES, timeout=1.0)[0]
    y = np.frombuffer(wf.samples, dtype=np.float64)
    n = y.size
    t_rel = np.arange(n) * scope_dt
    return t_rel, y

# ------------ Preview synthesis (matches NI-FGEN standard shapes) ------------
def synth_standard_chunk(waveform_name: str, f_hz: float, a_vpp: float, n: int, fs: float, phase0: float):
    """
    Generate n samples of the selected shape. Amplitude is Vpp. Returns (y, phase_out).
    """
    dt = 1.0 / fs
    t = np.arange(n) * dt
    A = a_vpp / 2.0
    phase = phase0 + 2 * np.pi * f_hz * t

    if waveform_name == "SINE":
        y = A * np.sin(phase)

    elif waveform_name == "SQUARE":
        y = A * np.sign(np.sin(phase))
        y[y == 0] = A

    elif waveform_name == "TRIANGLE":
        frac = ((phase / (2*np.pi)) + 0.25) % 1.0
        y = A * (4 * np.abs(frac - 0.5) - 1)

    elif waveform_name == "RAMP_UP":
        frac = (phase / (2*np.pi)) % 1.0
        y = A * (2*frac - 1)

    elif waveform_name == "RAMP_DOWN":
        frac = (phase / (2*np.pi)) % 1.0
        y = A * (1 - 2*frac)

    else:  # NOISE
        rng = np.random.default_rng()
        y = rng.normal(0.0, A/2, n)

    phase_out = (phase0 + 2 * np.pi * f_hz * n * dt) % (2*np.pi)
    return y, phase_out


def save_recording_to_file(x_values, y_values):
    """Write recorded waveform data to a timestamped txt file."""
    if not x_values or not y_values:
        return None
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path = DOWNLOAD_DIR / filename
    with path.open("w", encoding="utf-8") as record_file:
        record_file.write("time_us\tvoltage_v\n")
        for x_val, y_val in zip(x_values, y_values):
            record_file.write(f"{x_val}\t{y_val}\n")
    return str(path)


def reset_recording_buffer():
    with recording_lock:
        recording_buffer["x"].clear()
        recording_buffer["y"].clear()


def append_recording_data(x_points, y_points):
    with recording_lock:
        recording_buffer["x"].extend(x_points)
        recording_buffer["y"].extend(y_points)


def snapshot_recording_data():
    with recording_lock:
        return recording_buffer["x"][:], recording_buffer["y"][:]

# ------------ Dash app ------------
app = dash.Dash(__name__)
app.title = "NI-FGEN Real-Time Plot"

APP_BACKGROUND_STYLE = {
    "backgroundColor": "#edf1f7",
    "minHeight": "100vh",
}

CONTENT_STYLE = {
    "maxWidth": "960px",
    "margin": "0 auto",
    "padding": "0 24px 40px",
}

PRIMARY_BUTTON_STYLE = {
    "backgroundColor": "#1f77b4",
    "color": "white",
    "padding": "12px 20px",
    "fontSize": "16px",
    "border": "none",
    "borderRadius": "6px",
    "cursor": "pointer",
}

STOP_BUTTON_STYLE = {
    **PRIMARY_BUTTON_STYLE,
    "backgroundColor": "#d9534f",
}

RECORD_BUTTON_STYLE = {
    **PRIMARY_BUTTON_STYLE,
    "backgroundColor": "#ff9800",
}

RECORD_BUTTON_ACTIVE_STYLE = {
    **RECORD_BUTTON_STYLE,
    "backgroundColor": "#e65100",
}

AUTOSCALE_LABEL = "⇱ Auto-scale to frequency"

WAVEFORM_ICON_MAP = {
    "SINE": "mdi:sine-wave",
    "SQUARE": "mdi:square-wave",
    "TRIANGLE": "mdi:triangle-wave",
    "NOISE": "mdi:waveform",
    "RAMP_UP": "mdi:sawtooth-wave",
    "RAMP_DOWN": "mdi:sawtooth-wave",
}

WAVEFORM_BUTTON_STYLE = {
    "border": "2px solid #1f77b4",
    "padding": "8px 14px",
    "borderRadius": "6px",
    "cursor": "pointer",
    "display": "flex",
    "alignItems": "center",
    "gap": "6px",
    "backgroundColor": "#f5f8ff",
    "color": "#1f77b4",
    "fontWeight": "600",
    "boxShadow": "0 2px 5px rgba(0,0,0,0.08)",
    "transition": "all 0.15s ease",
}

WAVEFORM_BUTTON_SELECTED_STYLE = {
    "backgroundColor": "#1f77b4",
    "color": "white",
    "boxShadow": "0 3px 10px rgba(31, 119, 180, 0.35)",
}

UNIT_BUTTON_STYLE = {
    "border": "1px solid #555",
    "padding": "6px 12px",
    "borderRadius": "6px",
    "cursor": "pointer",
    "backgroundColor": "white",
    "color": "#333",
    "fontWeight": "600",
    "borderRadius": "999px",
}

UNIT_BUTTON_SELECTED_STYLE = {
    "backgroundColor": "#1f77b4",
    "color": "white",
    "border": "1px solid #1f77b4",
    "boxShadow": "0 2px 6px rgba(31,119,180,0.4)",
}

CONTROL_CARD_STYLE = {
    "backgroundColor": "white",
    "borderRadius": "16px",
    "padding": "20px 24px 28px",
    "boxShadow": "0 10px 25px rgba(15, 23, 42, 0.08)",
}

SECTION_LABEL_STYLE = {
    "fontWeight": "700",
    "fontSize": "14px",
    "color": "#475467",
}

GRAPH_CARD_STYLE = {
    "border": "1px solid #d4d4d4",
    "borderRadius": "16px",
    "padding": "16px",
    "marginTop": "16px",
    "backgroundColor": "#fefefe",
    "boxShadow": "0 15px 30px rgba(0,0,0,0.08)",
}

INSTRUCTION_CARD_STYLE = {
    "backgroundColor": "white",
    "borderRadius": "16px",
    "padding": "24px",
    "boxShadow": "0 12px 28px rgba(15, 23, 42, 0.12)",
    "color": "#1d2a44",
    "width": "360px",
}

INSTRUCTION_STEPS = [
    "Confirm the NI-FGEN and (optional) NI-SCOPE sessions are cabled and the resource aliases in the config block match your chassis.",
    "Choose a waveform at the top. The highlighted button shows which standard shape will be programmed when you press Configure & Start.",
    "Set the desired frequency using the slider or by typing an exact value. Pick Hz/kHz/MHz to match the magnitude. Do the same for amplitude, keeping the value below 12 Vpp.",
    "Press Configure & Start to send the settings to the hardware. The status label will show the active waveform, frequency, and amplitude.",
    "Use Stop to abort any generation. If you enabled recording, the .txt log of the preview trace is saved into your Downloads folder when you stop.",
    "The Auto-scale button resizes the preview window to lock onto the incoming frequency. Keep an eye on the card at the bottom for live feedback and waveform preview.",
]

def build_icon_label(icon_name, text):
    return [
        DashIconify(icon=icon_name, width=20, color="currentColor"),
        html.Span(text, style={"marginLeft": "6px"}),
    ]


def build_autoscale_children(is_on):
    label = f"{AUTOSCALE_LABEL} (ON)" if is_on else AUTOSCALE_LABEL
    return build_icon_label("mdi:axis-arrow-expand", label)


def build_record_button_children(is_recording):
    if is_recording:
        return build_icon_label("mdi:stop-circle", "Recording...")
    return build_icon_label("mdi:record-circle", "Start Recording")

app.layout = html.Div(
    style=APP_BACKGROUND_STYLE,
    children=[
        html.H3(
            "NI-FGEN Control and Real-Time Plot",
            style={
                "textAlign": "center",
                "fontFamily": "'Segoe UI', 'Helvetica Neue', sans-serif",
                "fontWeight": "800",
                "letterSpacing": "0.5px",
                "color": "#0f172a",
                "marginBottom": "18px",
                "paddingTop": "30px",
            },
        ),
        html.Div(
            style={
                "display": "flex",
                "maxWidth": "1250px",
                "margin": "0 auto",
                "gap": "26px",
                "alignItems": "flex-start",
                "padding": "0 20px 40px",
            },
            children=[
                html.Div(
                    style={"flex": "1", "display": "flex", "flexDirection": "column", "gap": "18px"},
                    children=[
                        html.Div(
                            style=CONTROL_CARD_STYLE,
                            children=[
                                html.Label("Waveform", style=SECTION_LABEL_STYLE),
                                html.Div(
                                    id="waveform-buttons",
                                    style={"display": "flex", "flexWrap": "wrap", "gap": "10px"},
                                    children=[
                                        html.Button(
                                            [
                                                DashIconify(
                                                    icon=WAVEFORM_ICON_MAP.get(wf.name, "mdi:waveform"),
                                                    width=22,
                                                    color="currentColor",
                                                ),
                                                html.Span(wf.name.replace("_", " ").title()),
                                            ],
                                            id={"type": "wf-btn", "wf": wf.name},
                                            n_clicks=0,
                                            style=WAVEFORM_BUTTON_STYLE,
                                        )
                                        for wf in MyWaveform
                                    ],
                                ),

                                html.Div(
                                    style={"marginTop": "18px"},
                                    children=[
                                        html.Label("Frequency", style=SECTION_LABEL_STYLE),
                                        html.Div(
                                            style={"display": "flex", "gap": "12px", "alignItems": "center"},
                                            children=[
                                                html.Div(
                                                    dcc.Slider(
                                                        id="freq-slider",
                                                        min=1,
                                                        max=1000,
                                                        step=1,
                                                        value=1,
                                                        marks={1: "1", 250: "250", 500: "500", 750: "750", 1000: "1000"},
                                                        tooltip={"placement": "bottom", "always_visible": True},
                                                    ),
                                                    style={"flex": "1"},
                                                ),
                                                dcc.Input(
                                                    id="freq-input",
                                                    type="number",
                                                    min=1,
                                                    max=1000,
                                                    step=1,
                                                    value=1,
                                                    debounce=True,
                                                    style={
                                                        "width": "110px",
                                                        "padding": "8px 10px",
                                                        "border": "1px solid #cbd5e1",
                                                        "borderRadius": "8px",
                                                        "fontSize": "15px",
                                                        "color": "#0f172a",
                                                        "boxShadow": "inset 0 1px 2px rgba(15,23,42,0.12)",
                                                    },
                                                ),
                                            ],
                                        ),
                                    ],
                                ),

                                html.Div(
                                    style={"marginTop": "18px"},
                                    children=[
                                        html.Label("Units", style=SECTION_LABEL_STYLE),
                                        html.Div(
                                            id="freq-unit-buttons",
                                            style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "marginTop": "6px"},
                                            children=[
                                                html.Button(
                                                    FREQ_UNIT_LABELS[unit],
                                                    id={"type": "freq-unit-btn", "unit": unit},
                                                    n_clicks=0,
                                                    style=UNIT_BUTTON_STYLE,
                                                )
                                                for unit in FREQ_UNIT_OPTIONS
                                            ],
                                        ),
                                    ],
                                ),

                                html.Div(
                                    style={"marginTop": "18px"},
                                    children=[
                                        html.Label(f"Amplitude (Vpp, max {MAX_VPP})", style=SECTION_LABEL_STYLE),
                                        # Same combo as frequency so typed values enforce HW limits.
                                        html.Div(
                                            style={"display": "flex", "gap": "12px", "alignItems": "center"},
                                            children=[
                                                html.Div(
                                                    dcc.Slider(
                                                        id="amp-slider",
                                                        min=0.1,
                                                        max=MAX_VPP,
                                                        step=0.1,
                                                        value=1.0,
                                                        marks={0: "0", 3: "3", 6: "6", 9: "9", 12: "12"},
                                                        tooltip={"placement": "bottom", "always_visible": True},
                                                    ),
                                                    style={"flex": "1"},
                                                ),
                                                dcc.Input(
                                                    id="amp-input",
                                                    type="number",
                                                    min=0.1,
                                                    max=MAX_VPP,
                                                    step=0.1,
                                                    value=1.0,
                                                    debounce=True,
                                                    style={
                                                        "width": "110px",
                                                        "padding": "8px 10px",
                                                        "border": "1px solid #cbd5e1",
                                                        "borderRadius": "8px",
                                                        "fontSize": "15px",
                                                        "color": "#0f172a",
                                                        "boxShadow": "inset 0 1px 2px rgba(15,23,42,0.12)",
                                                    },
                                                ),
                                            ],
                                        ),
                                    ],
                                ),

                                html.Div(
                                    style={"marginTop": "24px", "display": "flex", "gap": "10px", "flexWrap": "wrap"},
                                    children=[
                                        html.Button(
                                            build_icon_label("mdi:play", "Configure & Start"),
                                            id="start-btn",
                                            n_clicks=0,
                                            title="Configure NI-FGEN and begin waveform generation",
                                            style=PRIMARY_BUTTON_STYLE,
                                        ),
                                        html.Button(
                                            build_icon_label("mdi:stop", "Stop"),
                                            id="stop-btn",
                                            n_clicks=0,
                                            title="Abort the waveform output",
                                            style=STOP_BUTTON_STYLE,
                                        ),
                                        html.Button(
                                            build_record_button_children(False),
                                            id="record-btn",
                                            n_clicks=0,
                                            title="Capture waveform preview data to a text file",
                                            style=RECORD_BUTTON_STYLE,
                                        ),
                                        html.Button(
                                            build_autoscale_children(False),
                                            id="autoscale-btn",
                                            n_clicks=0,
                                            title="Resize the preview window to display several cycles",
                                            style=PRIMARY_BUTTON_STYLE,
                                        ),
                                    ],
                                ),
                            ],
                        ),

                        html.Div(
                            id="save-message",
                            style={
                                "textAlign": "left",
                                "margin": "0 0 8px 0",
                                "fontWeight": "600",
                                "fontSize": "15px",
                                "color": "#0f172a",
                            },
                        ),
                        html.Div(
                            style=GRAPH_CARD_STYLE,
                            children=[
                                html.Div(
                                    id="status",
                                    style={
                                        "fontWeight": "bold",
                                        "paddingBottom": "6px",
                                        "marginBottom": "12px",
                                        "borderBottom": "1px solid #e3e3e3",
                                    },
                                ),
                                dcc.Graph(
                                    id="waveform-preview",
                                    figure=go.Figure(
                                        data=[go.Scatter(x=[], y=[], mode="lines", name="Signal")],
                                        layout=go.Layout(
                                            height=420,
                                            xaxis_title="Time (µs, relative)",
                                            yaxis_title="Voltage (V)",
                                            margin=dict(l=40, r=20, t=30, b=40),
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),

                html.Div(
                    style={"width": "380px"},
                    children=[
                        html.Div(
                            style=INSTRUCTION_CARD_STYLE,
                            children=[
                                html.H4("How to use this panel", style={"fontWeight": "800"}),
                                html.Ol(
                                    [
                                        html.Li(step, style={"marginBottom": "10px", "lineHeight": "2.0"})
                                        for step in INSTRUCTION_STEPS
                                    ],
                                    style={"paddingLeft": "18px"},
                                ),
                                html.P(
                                    "Tip: when recording, let the preview run as long as needed before pressing Stop.",
                                    style={"fontStyle": "italic", "marginTop": "18px"},
                                ),
                            ],
                        )
                    ],
                ),
            ],
        ),
        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0, disabled=True),
        dcc.Store(id="last-cfg"),
        dcc.Store(id="sim-phase", data=0.0),
        dcc.Store(id="x-last", data=0.0),
        dcc.Store(id="running", data=False),
        dcc.Store(id="autoscale-on", data=False),
        dcc.Store(id="waveform-selected", data="SINE"),
        dcc.Store(id="freq-unit-selected", data="MHZ"),
        dcc.Store(id="recording", data=False),
    ],
)

# ------------- Callbacks -------------
@app.callback(
    Output("waveform-selected", "data"),
    Output({"type": "wf-btn", "wf": ALL}, "style"),
    Input({"type": "wf-btn", "wf": ALL}, "n_clicks"),
    State("waveform-selected", "data"),
)
def choose_waveform(n_clicks_list, current_selection):
    triggered = ctx.triggered_id
    selected = current_selection
    if isinstance(triggered, dict) and triggered.get("wf"):
        selected = triggered["wf"]

    styles = []
    for wf_name in WAVEFORM_NAMES:
        style = WAVEFORM_BUTTON_STYLE.copy()
        if wf_name == selected:
            style.update(WAVEFORM_BUTTON_SELECTED_STYLE)
        styles.append(style)

    return selected, styles


@app.callback(
    Output("freq-unit-selected", "data"),
    Output({"type": "freq-unit-btn", "unit": ALL}, "style"),
    Input({"type": "freq-unit-btn", "unit": ALL}, "n_clicks"),
    State("freq-unit-selected", "data"),
)
def choose_freq_unit(n_clicks_list, current_selection):
    triggered = ctx.triggered_id
    selected = current_selection
    if isinstance(triggered, dict) and triggered.get("unit"):
        selected = triggered["unit"]

    styles = []
    for unit in FREQ_UNIT_OPTIONS:
        style = UNIT_BUTTON_STYLE.copy()
        if unit == selected:
            style.update(UNIT_BUTTON_SELECTED_STYLE)
        styles.append(style)
    return selected, styles


@app.callback(
    Output("freq-slider", "value"),
    Output("freq-input", "value"),
    Input("freq-slider", "value"),
    Input("freq-input", "value"),
    prevent_initial_call=True
)
def sync_frequency(slider_value, input_value):
    """Keep slider/input for frequency consistent, clamping to the allowed bounds."""
    trigger = ctx.triggered_id
    slider_value = slider_value or 1
    input_value = input_value or 1
    input_value = max(min(input_value, 1000), 1)
    if trigger == "freq-slider":
        return slider_value, slider_value
    return input_value, input_value


@app.callback(
    Output("amp-slider", "value"),
    Output("amp-input", "value"),
    Input("amp-slider", "value"),
    Input("amp-input", "value"),
    prevent_initial_call=True
)
def sync_amplitude(slider_value, input_value):
    """Same as sync_frequency but for the amplitude controls."""
    trigger = ctx.triggered_id
    slider_value = slider_value or 0.1
    input_value = input_value or 0.1
    input_value = max(min(input_value, MAX_VPP), 0.1)
    if trigger == "amp-slider":
        return slider_value, slider_value
    return input_value, input_value


@app.callback(
    Output("recording", "data"),
    Input("record-btn", "n_clicks"),
    State("recording", "data"),
    prevent_initial_call=True
)
def toggle_record_button(_, is_recording):
    """Toggle capture mode; when entering recording we clear any previous data."""
    new_state = not bool(is_recording)
    if new_state:
        reset_recording_buffer()
    return new_state


@app.callback(
    Output("record-btn", "children"),
    Output("record-btn", "style"),
    Input("recording", "data")
)
def update_record_button_ui(is_recording):
    style = RECORD_BUTTON_ACTIVE_STYLE if is_recording else RECORD_BUTTON_STYLE
    children = build_record_button_children(bool(is_recording))
    return children, style


@app.callback(
    Output("status", "children"),
    Output("last-cfg", "data"),
    Output("running", "data"),
    Output("save-message", "children", allow_duplicate=True),
    Input("start-btn", "n_clicks"),
    State("waveform-selected", "data"),
    State("freq-slider", "value"),
    State("freq-unit-selected", "data"),
    State("amp-slider", "value"),
    prevent_initial_call=True
)
def on_start(_, waveform_name, freq_value, freq_unit, amp_vpp):
    if amp_vpp > MAX_VPP:
        return f"Amplitude {amp_vpp} exceeds {MAX_VPP} Vpp.", dash.no_update, False, dash.no_update

    unit_factor = UNIT_FACTORS.get(freq_unit, 1.0)
    freq_hz = freq_value * unit_factor
    wf_enum = MyWaveform[waveform_name]

    try:
        configure_fgen(wf_enum, freq_hz, amp_vpp)
        if USE_SCOPE:
            ensure_scope()
    except Exception as e:
        return f"Error configuring hardware: {e}", dash.no_update, False, dash.no_update

    unit_label = FREQ_UNIT_LABELS.get(freq_unit, freq_unit)
    status = f"{waveform_name} running at {freq_value:.3f} {unit_label}, {amp_vpp:.2f} Vpp"
    cfg = {
        "wf": waveform_name,
        "freq_value": freq_value,
        "freq_unit": freq_unit,
        "freq_hz": freq_hz,
        "amp": amp_vpp,
    }
    return status, cfg, True, ""

@app.callback(
    Output("status", "children", allow_duplicate=True),
    Output("running", "data", allow_duplicate=True),
    Output("x-last", "data", allow_duplicate=True),
    Output("sim-phase", "data", allow_duplicate=True),
    Output("recording", "data", allow_duplicate=True),
    Output("save-message", "children", allow_duplicate=True),
    Input("stop-btn", "n_clicks"),
    State("recording", "data"),
    prevent_initial_call=True
)
def on_stop(_, is_recording):
    """Abort NI-FGEN and stop streaming."""
    global fgen
    status_msg = "No active session."
    with fgen_lock:
        if fgen is None:
            status_msg = "No active session."
        else:
            try:
                fgen.abort()
                status_msg = "Waveform generation stopped."
            except Exception as e:
                status_msg = f"Error stopping: {e}"

    save_message = ""
    if is_recording:
        x_vals, y_vals = snapshot_recording_data()
        saved_path = save_recording_to_file(x_vals, y_vals)
        reset_recording_buffer()
        if saved_path:
            status_msg += f" Recording saved to {saved_path}."
            save_message = f"Recording saved to {saved_path}"
        else:
            status_msg += " Recording data unavailable."

    return status_msg, False, 0.0, 0.0, False, save_message

@app.callback(
    Output("tick", "disabled"),
    Input("running", "data")
)
def control_timer(is_running):
    """Enable/disable the timer based on running state."""
    return not bool(is_running)

@app.callback(
    Output("autoscale-on", "data"),
    Output("autoscale-btn", "children"),
    Input("autoscale-btn", "n_clicks"),
    State("autoscale-on", "data"),
    prevent_initial_call=True
)
def toggle_autoscale(_, current):
    new_state = not bool(current)
    children = build_autoscale_children(new_state)
    return new_state, children

@app.callback(
    Output("waveform-preview", "extendData"),
    Output("x-last", "data"),
    Output("sim-phase", "data"),
    Input("tick", "n_intervals"),
    State("last-cfg", "data"),
    State("x-last", "data"),
    State("sim-phase", "data"),
    State("autoscale-on", "data"),
    State("recording", "data"),
    prevent_initial_call=True
)
def stream_data(_, cfg, x_last, sim_phase, autoscale_on, recording):
    """Append a small chunk every tick. Rolling window can auto-scale by frequency."""
    if cfg is None:
        raise dash.exceptions.PreventUpdate
    freq_value = cfg.get("freq_value", 0.0)
    unit = cfg.get("freq_unit", "HZ")
    freq_hz = cfg.get("freq_hz", freq_value * UNIT_FACTORS.get(unit, 1.0))
    freq_hz = float(freq_hz or 0.0)
    autoscale_active = bool(autoscale_on) and freq_hz > 0

    if USE_SCOPE:
        t_rel, y = fetch_scope_chunk()
        fs = 1.0 / scope_dt
        if autoscale_active:
            desired_points = max(int(AUTO_CYCLES * fs / freq_hz), 500)
            desired_points = min(desired_points, len(y))
            if desired_points <= 0:
                desired_points = len(y)
            y = y[-desired_points:]
            t_rel = np.arange(desired_points) / fs
    else:
        chunk_len = PREVIEW_CHUNK
        if autoscale_active:
            chunk_len = max(int(AUTO_CYCLES * AUTOSCALE_SAMPLES_PER_PERIOD), 500)
            if freq_hz > 0:
                effective_fs = freq_hz * AUTOSCALE_SAMPLES_PER_PERIOD
            else:
                effective_fs = PREVIEW_FS
            y, _ = synth_standard_chunk(
                cfg["wf"], freq_hz, cfg["amp"], n=chunk_len, fs=effective_fs, phase0=0.0
            )
            sim_phase = 0.0
            fs = effective_fs
        else:
            y, sim_phase = synth_standard_chunk(
                cfg["wf"], freq_hz, cfg["amp"], n=chunk_len, fs=PREVIEW_FS, phase0=sim_phase
            )
            fs = PREVIEW_FS
        t_rel = np.arange(y.size) / fs

    if autoscale_active:
        x = t_rel
        x_last = 0.0
        window_points = len(y) if len(y) > 0 else DEFAULT_WINDOW_POINTS
    else:
        x = x_last + t_rel
        x_last = float(x[-1]) if x.size else float(x_last)
        window_points = DEFAULT_WINDOW_POINTS

    extend = ({"x": [list(x * 1e6)], "y": [list(y)]}, [0], window_points)

    if recording:
        append_recording_data(list(x * 1e6), list(y))

    return extend, x_last, sim_phase

if __name__ == "__main__":
    app.run(debug=False)
