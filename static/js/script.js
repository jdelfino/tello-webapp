document.addEventListener("DOMContentLoaded", function(event) {
  var socket = io.connect('http://127.0.0.1:5000');
  console.log("connected")

  const image_element=document.getElementById('image1');

  socket.on('VS', function (data) {
      image_element.src="data:image/jpeg;base64," + data;
   });

  socket.on('update value', function(msg) {
    console.log('value updated', msg);
    document.getElementById('#counter').textContent = msg.msg
  });

  height_graph_div = document.getElementById('height-graph');
  console.log(height_graph_div);
  height_plot = Plotly.newPlot(height_graph_div,
    [{ x: [], y: [] }],
    {
      xaxis: {
        rangemode: 'nonnegative',
        autorange: true
      },
      margin: { t: 0 },
    }
  );

  socket.on('data', function(msg) {
    document.querySelector('#height-cell').textContent = msg['height_cm'];
    Plotly.extendTraces(height_graph_div, {
      x: [[msg['time_s']]],
      y: [[msg['height_cm']]]
    }, [0]);
    document.querySelector('#speed-x-cell').textContent = msg['speed_x'];
    document.querySelector('#speed-y-cell').textContent = msg['speed_y'];
    document.querySelector('#speed-z-cell').textContent = msg['speed_z'];
    document.querySelector('#pitch-cell').textContent = msg['pitch'];
    document.querySelector('#yaw-cell').textContent = msg['yaw'];
    document.querySelector('#roll-cell').textContent = msg['roll'];
    document.querySelector('#battery-cell').textContent = msg['battery'];
    if(msg['command']){
      document.querySelector('#command-cell').textContent = msg['command'] + " (" + Math.round(msg['time_s']) + ")";
    }
  });

  emergency_stop_button = document.getElementById('emergency-stop-button');
  drone_video_button = document.getElementById('dl-drone-video-button');
  cam_video_button = document.getElementById('dl-cam-video-button');
  data_button = document.getElementById('dl-csv-button');
  error_text = document.getElementById('error-text');

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
    console.log("flight finished");
    console.log(msg);
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
    console.log('After connect', msg);
  })

  socket.on("connect_error", (err) => {
  console.log(`connect_error due to ${err.message}`);
  });

  commands_text_area = document.getElementById('moves-text-area');
  commands_text_area.value = localStorage.getItem('moves-text-area');

  document.querySelector('#launch-button').addEventListener("click", function () {
    show_emergency_stop_button();

    socket.emit('launch', {'moves': commands_text_area.value});
  });

  document.querySelector('#stop-button').addEventListener("click", function () {
    socket.emit('stop', {});
  });

  document.querySelector('#emergency-stop-button').addEventListener("click", function () {
    socket.emit('emergency_stop', {});
  });
});

window.addEventListener("beforeunload", function(){
  commands_text_area = document.getElementById('moves-text-area');
  localStorage.setItem('moves-text-area', commands_text_area.value);
});
