var socket = null;

document.addEventListener("DOMContentLoaded", function(event) {
  if(!socket) { socket = io.connect(); }
  console.log("connected")

  let drone_video_img = document.getElementById('drone-video');
  let emergency_stop_button = document.getElementById('emergency-stop-button');
  let drone_video_button = document.getElementById('dl-drone-video-button');
  let cam_video_button = document.getElementById('dl-cam-video-button');
  let data_button = document.getElementById('dl-csv-button');
  let error_text = document.getElementById('error-text');

  function show_emergency_stop_button() {
    emergency_stop_button.style.display = "block";
    drone_video_button.style.display = "none";
    cam_video_button.style.display = "none";
    data_button.style.display = "none";
    error_text.style.display = "none";
  }

  function show_download_buttons() {
    emergency_stop_button.style.display = "none";
    drone_video_button.style.display = "block";
    cam_video_button.style.display = "block";
    data_button.style.display = "block";
    error_text.style.display = "none";
  }

  function show_error_message() {
    emergency_stop_button.style.display = "none";
    drone_video_button.style.display = "none";
    cam_video_button.style.display = "none";
    data_button.style.display = "none";
    error_text.style.display = "block";
  }

  socket.on('flight_finished', function(msg) {
    console.log("flight finished", msg);
    show_download_buttons();

    if('drone_video' in msg) {
      drone_video_button.href = msg['drone_video'];
      drone_video_button.download = 'drone_video.mp4';
      drone_video_button.classList.remove("disabled");
    } else {
      drone_video_button.classList.add("disabled");
    }

    if('cam_video' in msg) {
      cam_video_button.href = msg['cam_video']
      cam_video_button.download = 'cam_video.mp4'
    } else {
      cam_video_button.classList.add("disabled");
    }

    if('data_csv' in msg) {
      data_button.href = msg['data_csv']
      data_button.download = 'data.csv'
    } else {
      data_button.classList.add("disabled");
    }
  });

  socket.on('flight_failed', function(msg){
    error_text.textContent = "Flight failed. Reboot the drone and try again. Detailed message: \"" + msg['msg'] + "\"";
    show_error_message();
  });

  socket.on('after connect', function(msg){
  })

  socket.on("connect_error", (err) => {
    console.log(`connect_error due to ${err.message}`);
  });

  socket.on("wifi_status", function(msg){
    wifi_obj = document.getElementById('wifi-status');
    let val = msg['ssid'];
    let color = 'black';
    let fontw = 'normal';
    let bgcolor = 'transparent'
    if(!val) {
      val = "Not connected";
      color = 'white';
      fontw = 'bold';
      bgcolor = 'red';
    }
    wifi_obj.textContent = val;
    wifi_obj.style.color = color;
    wifi_obj.style['background-color'] = bgcolor;
    wifi_obj.style['font-weight'] = fontw;
  });

  document.querySelector('#launch-button')?.addEventListener("click", function () {
    show_emergency_stop_button();

    socket.emit('launch', {
      'moves': commands_text_area.value,
      'stream_drone_video': drone_video_img ? true : false,
      'record_webcam': true,
      'record_drone': true
    });
  });

  document.querySelector('#launch-wait-button')?.addEventListener("click", function () {
    show_emergency_stop_button();

    socket.emit('launch', {
      'wait': true,
      'stream_drone_video': drone_video_img ? true : false,
      'record_drone': true,
      'record_webcam': true
    });
  });

  document.querySelectorAll('.command-btn').forEach((element) => {
    element.addEventListener("click", function (event) {
      socket.emit('move', {'command': event.target.dataset.command});
    });
  });

  document.querySelector('#stop-button')?.addEventListener("click", function () {
    socket.emit('stop', {});
  });

  document.querySelector('#emergency-stop-button')?.addEventListener("click", function () {
    socket.emit('emergency_stop', {});
  });
});
