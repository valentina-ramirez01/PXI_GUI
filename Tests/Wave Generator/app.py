import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import plotly.graph_objs as go
import nifgen
from enum import Enum
import threading
import numpy as np

MAX_VP = 12.0  # PXIe-5413 maximum amplitude
RESOURCE_NAME = "Func_Gen"  # Replace with your PXIe-5413 resource string

# --- Enum for waveforms ---
class MyWaveform(Enum):
    SINE = nifgen.Waveform.SINE
    SQUARE = nifgen.Waveform.SQUARE
    TRIANGLE = nifgen.Waveform.TRIANGLE
    NOISE = nifgen.Waveform.NOISE
    RAMP_UP = nifgen.Waveform.RAMP_UP
    RAMP_DOWN = nifgen.Waveform.RAMP_DOWN


options = [
    {"label": wf.name.replace("_", " ").title(), "value": wf.name}
    for wf in MyWaveform
]  + [{"label": "Custom", "value": "CUSTOM"}]


# Custom Waveform presets
presets = {
    "Sine^3": "sin(2*pi*x)**3",
    "Chirp": "sin(2*pi*x**2)",
    "Exponential Decay": "exp(-5*x)*sin(10*pi*x)"
}

# Shared session lock
session_lock = threading.Lock()
session = None


# --- Functions ---
def configure_waveform(session, waveform_enum, freq, amp):
    """Configure the waveform on the NI-FGEN hardware."""
    session.abort()  # stop any previous generation
    session.configure_standard_waveform(
        waveform=waveform_enum.value,
        amplitude=amp,
        frequency=freq,
        dc_offset=0.0,
        start_phase=0.0,
    )
    session.output_mode = nifgen.OutputMode.FUNC
    session.initiate()
    print(f"→ {waveform_enum.name} at {freq} Hz, {amp} Vp")


# -------------------------------
# Dash App
# -------------------------------
app = dash.Dash(__name__)
app.title = "NI-FGEN Control Panel"

app.layout = html.Div([
    html.H2("NI-FGEN Waveform Generator", style={"textAlign": "center"}),

    html.Div([
        html.Label("Select waveform:"),
        dcc.Dropdown(
            id="waveform-dropdown",
            options=options,
            value="SINE",
            clearable=False,
        ),
        html.Br(),

        html.Label("Frequency:"),
        html.Div([
            dcc.Slider(
                id="freq-slider",
                min=1,
                max=1000,
                step=1,
                value=1,
                marks={1: "1", 250: "250", 500: "500", 750: "750", 1000: "1000"},
                tooltip={"placement": "bottom", "always_visible": True}
            ),
            html.Div([
                html.Label("Units:"),
                dcc.Dropdown(
                    id="freq-unit",
                    options=[
                        {"label": "Hz", "value": "HZ"},
                        {"label": "kHz", "value": "KHZ"},
                        {"label": "MHz", "value": "MHZ"}
                    ],
                    value="MHZ",
                    clearable=False,
                    style={"width": "100px", "display": "inline-block", "marginLeft": "10px"}
                )
            ], style={"marginTop": "10px"})
        ]),
        html.Br(),

        html.Label(f"Amplitude (Vp, max {MAX_VP}):"),
        dcc.Slider(
            id="amp-slider",
            min=0.1,
            max=MAX_VP,
            step=0.1,
            value=1.0,
            marks={0: "0", 3: "3", 6: "6", 9: "9", 12: "12"},
            tooltip={"placement": "bottom", "always_visible": True}
        ),

        html.Br(), html.Br(),

        html.Button("Configure & Start", id="start-btn", n_clicks=0,
                    style={"backgroundColor": "#4CAF50", "color": "white", "padding": "10px"}),

        html.Button("Stop", id="stop-btn", n_clicks=0,
                    style={"marginLeft": "10px", "backgroundColor": "#f44336", "color": "white", "padding": "10px"}),

        html.Div(id="status", style={"marginTop": "20px", "fontWeight": "bold", "color": "#333"}),

        html.Hr(),

        dcc.Graph(id="waveform-preview")
    ], style={"width": "60%", "margin": "auto"})

])


# -------------------------------
# Callbacks
# -------------------------------
@app.callback(
    Output("status", "children"),
    Output("waveform-preview", "figure"),
    Input("start-btn", "n_clicks"),
    State("waveform-dropdown", "value"),
    State("freq-slider", "value"),
    State("freq-unit", "value"),
    State("amp-slider", "value"),
    prevent_initial_call=True
)
def start_waveform(n, waveform_name, freq_value, freq_unit, amp):
    """Start waveform generation on button press."""
    global session
    if amp > MAX_VP:
        return f"❌ Amplitude {amp} exceeds maximum {MAX_VP} Vp.", go.Figure()

    # Convert frequency based on unit
    unit_factor = {"HZ": 1, "KHZ": 1e3, "MHZ": 1e6}[freq_unit]
    freq = freq_value * unit_factor

    wf_enum = MyWaveform[waveform_name]

    try:
        with session_lock:
            if session is None:
                session = nifgen.Session(RESOURCE_NAME)
            configure_waveform(session, wf_enum, freq, amp)
    except Exception as e:
        return f"❌ Error: {e}", go.Figure()

    # Create a simple preview graph
    t = np.linspace(0, 1/freq, 1000)
    if waveform_name == "SINE":
        y = amp * np.sin(2 * np.pi * freq * t)
    elif waveform_name == "SQUARE":
        y = amp * np.sign(np.sin(2 * np.pi * freq * t))
    elif waveform_name in ["RAMP_UP", "RAMP_DOWN", "TRIANGLE"]:
        y = 2*amp*(2*(t*freq - np.floor(t*freq + 0.5)))
    else:
        y = np.random.normal(0, amp/2, len(t))

    fig = go.Figure(data=go.Scatter(x=t*1e6, y=y, mode="lines", name="Waveform"))
    fig.update_layout(title="Preview (simulated)", xaxis_title="Time (µs)", yaxis_title="Voltage (V)")

    return f"✅ {waveform_name} running at {freq_value:.2f} {freq_unit}, {amp:.2f} Vp", fig


@app.callback(
    Output("status", "children", allow_duplicate=True),
    Input("stop-btn", "n_clicks"),
    prevent_initial_call=True
)
def stop_waveform(n):
    """Stop waveform generation."""
    global session
    with session_lock:
        if session is not None:
            try:
                session.abort()
                return "🟥 Waveform generation stopped."
            except Exception as e:
                return f"❌ Error stopping: {e}"
    return "⚠️ No active session."


# -------------------------------
# Run app
# -------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8051, debug=False)
