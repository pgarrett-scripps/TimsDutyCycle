import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import numpy as np, matplotlib.pyplot as plt
import streamlit as st

st.header('Bruker Timstof Duty Cycle Monitor')

st.text("""
A Streamlit application to monitor duty cycle impacts for timstof series mass spectrometers. 
""")

with st.expander('Help'):
    st.text("""
    Upload the analysis.tdf file inside of the Bruker .d folder (raw folder). Leave frame_id_high and frame_id_low as
    default (0, 1) unless you know what you are doing. Click Run.
    """)

analysis_tdf = st.file_uploader(label='Upload TDF file', type=['.tdf'])
c1, c2 = st.columns(2)
frame_id_low = c1.number_input(label='Frame id low', value=1)
frame_id_high = c2.number_input(label='Frame id high', value=0)


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


if st.button('Run'):
    if not analysis_tdf:
        st.warning(f'Upload TDF file!')
        st.stop()

    with sqlite_connect(analysis_tdf) as conn:

        # check if range for frame ids where specified
        if frame_id_high == 0:
            frame_id_high = conn.execute("SELECT MAX(Id) from Frames").fetchone()[0]

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

        # print exp_frame_time
        st.write("Number of empty MS frames {}".format(empty_ms))
        st.write("Number of empty MSMS frames {}".format(empty_msms))
        st.write("Average abs(time excess) = {0:.2f} %".format(
            100 * np.mean(np.abs(timediffs - exp_frame_time)) / exp_frame_time))
        st.write("Average time excess = {0:.2f} %".format(100 * np.mean(timediffs - exp_frame_time) / exp_frame_time))
        st.write("Abs deviation from expected time {0:.6f}s".format(np.mean(timediffs - exp_frame_time)))
        if 1 < len(precsel_times):
            st.write("Average time precursor search + scheduling: {0:.3f}s".format((np.mean(precsel_times))))
        st.write("expected time for frame: {0}s".format(exp_frame_time))
        st.write("number of scans: {0}".format(numscans))
        st.write("trigger period: {0}".format(cycletime_sec))
        st.write("quench time: {0}".format(quenchtime_sec))

        # Plot results
        fig = plt.figure()
        plt.plot(ids[0:-1], timediffs)

        plt.plot(precsel_ids, precsel_times, 'o', alpha=0.1)
        plt.plot(submit_ids, submit_times, 'x', alpha=0.1)
        plt.plot([ids[0], ids[-1]], [exp_frame_time, exp_frame_time], color=[1, 0, 0])
        plt.legend(('time delta between consecutive frames', 'time for precsel + scheduling'))
        plt.ylabel('time / sec')
        plt.xlabel('frame number')
        plt.ylim([0, 0.6])
        st.pyplot(fig)
