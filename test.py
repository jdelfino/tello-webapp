import tello_subprocess


t = tello_subprocess.TelloSubprocess()

def handle_drone_video
with t.start_flight(
	drone_video='outdir/drone.mp4',
	fps = 1,
	drone_video_handler=handle_drone_video) as f:

    f.command('cw 1')
    f.command('ccw 1')
    time.sleep(5)

print("Finished")