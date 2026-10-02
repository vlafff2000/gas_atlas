"""Native light/dark themes for Gas Atlas v5, with themed screen charts."""
import streamlit as st
import plotly.graph_objects as go


def apply():
    # Let Streamlit own the palette, including menus, forms and canvas tables.
    # A fixed light CSS palette prevents its Settings / Theme switch from working.
    st.set_option('client.toolbarMode', 'viewer')
    st.markdown('''<style>
    .block-container {max-width:1660px;padding-top:1.4rem;padding-bottom:3rem}
    h1 {letter-spacing:-.7px;font-weight:650!important;font-size:2rem!important}
    h1,h2,h3 {color:var(--text-color)}
    [data-testid="stMetric"] {
        background:var(--secondary-background-color);
        border:1px solid rgba(125,140,150,.28);border-radius:9px;padding:17px 20px
    }
    [data-testid="stMetricLabel"] {opacity:.75}
    [data-testid="stMetricValue"] {font-weight:650}
    [data-testid="stPlotlyChart"] {
        background:var(--background-color);
        border:1px solid rgba(125,140,150,.28);border-radius:10px;overflow:hidden
    }
    [data-testid="stExpander"] {border-color:rgba(125,140,150,.28);border-radius:9px}
    .atlas-label {font-size:11px;font-weight:700;letter-spacing:1.6px;
        color:var(--text-color);opacity:.7;margin-bottom:5px}
    [data-testid="stAppDeployButton"],.stAppDeployButton,footer {display:none!important}
    [data-testid="stDecoration"] {display:none}
    </style>''', unsafe_allow_html=True)

    if st.session_state.get('classic_ui',True):
        st.markdown('''<style>
        [data-testid="stSidebar"] {background:#142f38;color:#e5eeee}
        [data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label,[data-testid="stSidebar"] p,[data-testid="stSidebar"] span {color:#e5eeee}
        [data-testid="stSidebar"] [data-baseweb="select"]>div,[data-testid="stSidebar"] input,
        [data-testid="stSidebar"] button {background:#1d3b45;color:#fff;border-color:#37535d}
        [data-testid="stSidebar"] [data-testid="stExpander"] {border-color:#37535d}
        [data-testid="stSidebar"] svg {color:#b6d6d9}
        [data-testid="stSidebar"] [role="radiogroup"] label {border-radius:7px;padding:5px 9px;margin:1px 0}
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background:#25544f}
        .atlas-label {color:#16746c;opacity:1}
        </style>''',unsafe_allow_html=True)


def heading(title, subtitle):
    st.markdown('<div class="atlas-label">ГАЗОВЫЙ АТЛАС / РАБОЧЕЕ ПРОСТРАНСТВО</div>',
                unsafe_allow_html=True)
    st.title(title)
    st.caption(subtitle)


def chart_for_screen(figure,copy_figure=True):
    """Clone for the native theme; keep the original white figure for export."""
    figure = go.Figure(figure) if copy_figure else figure
    figure.update_layout(template='streamlit', paper_bgcolor=None, plot_bgcolor=None,
                         font={'color':None}, title={'font':{'color':None}},
                         legend={'font':{'color':None}},
                         hoverlabel={'bgcolor':None, 'font':{'color':None}})
    for name in figure.layout:
        if name.startswith(('xaxis', 'yaxis')):
            figure.layout[name].update(gridcolor=None, zerolinecolor=None,
                linecolor=None, tickcolor=None, spikecolor=None,
                tickfont={'color':None}, title={'font':{'color':None}})
    return figure
