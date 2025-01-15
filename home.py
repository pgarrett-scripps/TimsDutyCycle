import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import numpy as np
import plotly.graph_objects as go
import streamlit as st

st.header('Bruker Timstof Duty Cycle Monitor')

st.text("""
A Streamlit application to monitor duty cycle impacts for Timstof acquisitions. 
""")

analysis_tdf = st.file_uploader(label='Upload TDF file', type=['.tdf'])
c1, c2 = st.columns(2)

c1, c2 = st.columns(2)

set_min = c1.checkbox('Set minimum frame ID')
if set_min:
    frame_id_low = c1.number_input('Frame ID low', value=1)
else:
    frame_id_low = None

set_max = c2.checkbox('Set maximum frame ID')
if set_max:
    frame_id_high = c2.number_input('Frame ID high', value=100)
else:
    frame_id_high = None

# assert that frame_id_high is greater than frame_id_low
if frame_id_high and frame_id_low:
    if frame_id_high < frame_id_low:
        st.warning(f'Frame ID high must be greater than Frame ID low!')
        st.stop()


@contextmanager
def sqlite_connect(db_bytes):
    fp = Path(str(uuid4()))
    fp.write_bytes(db_bytes.getvalue())
    conn = sqlite3.connect(str(fp))

    try:
        yield conn
    finally:
        conn.close()
        fp.unlink()


if st.button('Run', type='primary', use_container_width=True):
    if not analysis_tdf:
        st.warning(f'Upload TDF file!')
        st.stop()

    with sqlite_connect(analysis_tdf) as conn:

        # check if range for frame ids where specified
        if frame_id_high == None:
            frame_id_high = conn.execute("SELECT MAX(Id) from Frames").fetchone()[0]

        if frame_id_low == None:
            frame_id_low = conn.execute("SELECT MIN(Id) from Frames").fetchone()[0]

        # Plot MS1 TIC
        tmp = conn.execute(
            "SELECT Id, SummedIntensities FROM Frames WHERE MsMsType=0 AND Id BETWEEN {0} AND {1} ORDER BY Id".format(
                frame_id_low, frame_id_high)).fetchall()
        tic_ids = np.array([tuple[0] for tuple in tmp])
        tic_intensities = np.array([tuple[1] for tuple in tmp])

        # Get times for precursor selection + scheduling (scheduling is really small) and frame-acquisition times
        tmp = conn.execute(
            "SELECT f.Id, p.Value FROM Frames f JOIN Properties p ON p.Frame=f.Id AND p.Property=(SELECT Id FROM PropertyDefinitions WHERE PermanentName='PrecSel_CompleteTime') AND p.Value NOT NULL ORDER BY f.Id").fetchall()
        precsel_ids = [tuple[0] for tuple in tmp]
        precsel_times = [tuple[1] for tuple in tmp]
        tmp = conn.execute("SELECT Id, Time FROM Frames WHERE Id BETWEEN {0} AND {1} ORDER BY Id".format(frame_id_low,
                                                                                                         frame_id_high)).fetchall()
        ids = np.array([tuple[0] for tuple in tmp])
        times = np.array([tuple[1] for tuple in tmp])
        timediffs = times[1:] - times[0:-1]

        # Get frame-submission times
        tmp = conn.execute(
            "SELECT f.Id, p.Value FROM Frames f JOIN Properties p ON p.Frame=f.Id AND p.Property=(SELECT Id FROM PropertyDefinitions WHERE PermanentName='Timing_SubmitFrame') AND p.Value NOT NULL ORDER BY f.Id").fetchall()
        submit_ids = [tuple[0] for tuple in tmp]
        submit_times = [tuple[1] for tuple in tmp]


        # Get theoretical time per frame [us]
        def get_unique_value(query):
            tmp = conn.execute(query).fetchall()
            if len(tmp) != 1:
                raise RuntimeError('expect exactly one result row')
            return tmp[0][0]


        cycletime_sec = 1e-6 * get_unique_value(
            "SELECT DISTINCT(p.Value) FROM Properties p WHERE p.Property = (SELECT Id FROM PropertyDefinitions WHERE PermanentName='Digitizer_ExtractTriggerTime')")
        # print cycletime_sec
        numscans = get_unique_value("SELECT DISTINCT(NumScans) FROM Frames")
        # print numscans
        quenchtime_sec = 1e-3 * get_unique_value(
            "SELECT DISTINCT(p.Value) FROM Properties p WHERE p.Property = (SELECT Id FROM PropertyDefinitions WHERE PermanentName='Collision_QuenchTime_Set')")
        # print quenchtime_sec
        exp_frame_time = numscans * cycletime_sec + quenchtime_sec

        # number of empty MS frames
        empty_ms = get_unique_value("SELECT COUNT(*) FROM Frames WHERE NumPeaks=0 AND MsMsType=0")
        empty_msms = get_unique_value("SELECT COUNT(*) FROM Frames WHERE NumPeaks=0 AND MsMsType=8")

        # 3) Replace the block that starts with "fig = plt.figure()" with:
        fig = go.Figure()

        fig.add_trace(
            go.Scattergl(
                x=ids[0:-1],
                y=timediffs,
                mode='lines',
                name='consecutive frames time deltas'
            )
        )

        fig.add_trace(
            go.Scattergl(
                x=precsel_ids,
                y=precsel_times,
                mode='markers',
                name='precsel + scheduling times',
                opacity=0.3
            )
        )

        fig.add_trace(
            go.Scattergl(
                x=submit_ids,
                y=submit_times,
                mode='markers',
                name='frame submission times',
                opacity=0.3
            )
        )

        # Add a horizontal line for expected frame time:
        fig.add_shape(
            type='line',
            x0=ids[0],
            y0=exp_frame_time,
            x1=ids[-1],
            y1=exp_frame_time,
            line=dict(color='red', width=2)
        )

        fig.update_layout(
            yaxis_title='time / sec',
            xaxis_title='frame number',
            yaxis_range=[0, 0.6],
            legend_title_text=''
        )

        sample_name = conn.execute(
            "SELECT value FROM GlobalMetadata WHERE key='SampleName'"
        ).fetchone()[0]

        # Then, when setting up the layout for your figure:
        fig.update_layout(
            title=f"Duty Cycle Plot - Sample: {sample_name}",
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=1.02,
                xanchor='left',
                x=0
            )
        )

        st.plotly_chart(fig, use_container_width=True)
