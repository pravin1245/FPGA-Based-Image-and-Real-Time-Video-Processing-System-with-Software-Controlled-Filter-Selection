# FPGA-Based Satellite Image and Real-Time Video Processing System with Software-Controlled Filter Selection on the PYNQ-Z2 Platform

## 1. Project Overview

Our project is an FPGA-Based Multi-Image Processing System using the PYNQ-Z2 board. The main aim of our project is to perform different image-processing operations using FPGA hardware and provide a simple software interface through the Jupyter Notebook.

The important feature of our system is that the user can select the required image-processing operation through a software command, without changing the FPGA hardware design. The software provides the input image, selects the required operation, controls the hardware and displays the output, while the FPGA performs the main image-processing operation.

The same system also processes **video**. A video is handled as a sequence of frames: each frame is prepared in the same way as a single image (256 × 256, 8-bit grayscale) and passed through the same streaming pipeline and the same four filter cores, so **no new hardware is needed for video**. The system accepts three kinds of input: a **still image**, a **stored (saved) video file** and a **live video from a USB camera**.

Another important feature is that image and video processing is performed locally on the PYNQ-Z2 without requiring an internet connection. This approach can be useful in applications such as defence, surveillance and remote monitoring, where continuous internet connectivity may not always be available and image data may need to be processed locally.

## 2. Target Board and Hardware Platform

Our system is based on the **PYNQ-Z2 development board**, which uses the Xilinx Zynq-7000 SoC with the XC7Z020 FPGA device. It has two main sections: the Processing System and the Programmable Logic.

The Processing System contains an ARM Cortex-A9 processor and runs Linux, Python and Jupyter Notebook. It handles software commands, image and video-frame preparation, hardware control and result display.

The Programmable Logic is the FPGA section where the image-processing operations are implemented in hardware. Therefore, our project combines software control with FPGA-based image processing.

### PYNQ-Z2 Development Board
<img width="1911" height="1188" alt="image" src="https://github.com/user-attachments/assets/39a0d812-9b8c-44c3-b4f1-2db149e4f708" />


*Figure 1: PYNQ-Z2 development board used for the project.*

### Board Specifications

| Parameter | Specification |
|---|---|
| Development Board | PYNQ-Z2 |
| SoC | Xilinx Zynq-7000 (Zynq-7020) |
| FPGA Device | XC7Z020 (xc7z020clg400-1) |
| Processor | ARM Cortex-A9 (dual-core) |
| Memory | 512 MB DDR3 |
| Input Image / Frame Size | 256 × 256 pixels |
| Pixel Format | 8-bit grayscale |
| Total Number of Pixels | 65,536 |
| Design Target Clock | 120 MHz (single clock domain, FCLK_CLK0) |
| Input Sources | Still image, stored video file, live USB camera |
| Software Interface | Python and Jupyter Notebook |
| Data Transfer | AXI DMA and AXI4-Stream |
| Filter Selection | AXI GPIO (4-bit, one bit per filter) |
| Design Tool | Vivado 2024.2 (overlay: `Image_processing_system_test.bit`) |

## 3. System Working

First, we load the predefined software program (`%run predefined.py.ipynb`) containing the functions required to control our system. The user provides an input image through the software. The image is resized to 256 × 256 pixels and converted from a colour image into an 8-bit grayscale image. The prepared image contains 65,536 pixels and is stored in a buffer in the DDR memory of the PYNQ-Z2.

After the image is stored in memory, DMA (Direct Memory Access) transfers the image data from DDR memory toward the FPGA. DMA transfers image data efficiently without requiring the ARM processor to transfer every pixel individually. This allows the processor to focus mainly on software and control tasks.

For communication between the Processing System and the FPGA hardware, our design uses AXI interfaces. AXI4-Lite is mainly used for control and configuration, while AXI4-Stream transfers the continuous pixel data.

Once the image data enters the FPGA, the AXI Broadcaster distributes the input stream to the available image-processing paths. Our system supports four image-processing operations.

- **Gaussian Filter:** Smooths the image and reduces noise.
- **Sobel Filter:** Detects edges and boundaries.
- **Laplacian Filter:** Highlights rapid changes in image intensity and helps identify boundaries.
- **Canny Filter:** Performs detailed edge detection to obtain clearer edge information.

The four operations use three filter IP cores, because the Gaussian/Sobel core has two outputs. Each core is built around a BRAM-based line buffer that reconstructs a 3×3 neighbourhood from a single-pixel-per-clock raster stream.

The main feature of our project is software-controlled filter selection. The user selects the required processing path directly from the Jupyter Notebook using software commands.

When a command is executed, the software sends the required control information to the FPGA through AXI GPIO. The corresponding processing and output path is selected without changing or rebuilding the FPGA hardware design.

After the selected image-processing operation is completed, the processed pixel data passes through the corresponding output gate. The output gate controls which processing result is allowed to continue toward the output section. The processed data then passes through an AXI4-Stream FIFO, which provides temporary buffering for the pixel stream.

After the FIFO, the S2MM channel of the output DMA belonging to the selected filter transfers the processed image back to DDR memory. Once the DMA transfer is completed, the software reads the processed image from the output buffer. The result is then displayed in the Jupyter Notebook.

### Video Processing

For video, each frame goes through this same path in turn. The broadcaster, cores, gates, FIFOs and DMA channels are not changed, so the selected filter is applied to every frame with no change to the bitstream.

- **Stored video:** `input_video("sample_video.mp4")` opens a video file. ffmpeg decodes the video once, scales every frame to 256 × 256, and the frames are kept in RAM (up to 150 MB; a larger video is streamed instead of cached). If ffmpeg is not installed, the slower OpenCV decoder is used.
- **Live video:** `input_video("live_video")` finds a USB camera automatically (`/dev/video0` to `/dev/video3`) and asks it for 640 × 480 pixels at 30 frames per second in MJPG mode. Every camera frame is reduced to 256 × 256 in software. When the later stages are slower than the camera, the oldest frame is dropped instead of waiting, so the output always follows the newest picture. `set_camera_flip()` corrects an inverted picture (default is a 180° rotation).
- **Playback pipeline:** The video functions run three stages in separate threads joined by small queues: a reader that supplies the decoded or camera frames, an FPGA worker that converts each frame to grayscale, calls `fpga_frame()` for the selected filter and encodes the result as JPEG, and an output clock that sends one result to the display at the target rate.
- **Display:** The processed video is shown on a **separate web page served by the board itself** (an MJPEG stream, `http://<board-ip>:8000/`). The page shows only the video, scaled to fill the full width and height of the browser window, and a double click toggles full-screen mode. A side-by-side preview of the input and output frames is also shown in the notebook at 5 frames per second. `camera_view()` shows the camera picture alone, without any filter, to check the camera.

## 4. User Commands

The following Python commands are used through the Jupyter Notebook to control the image-processing operations.

### 4.1 Image Commands

First supply the image with `input_image("input_image.png")`, then run one of the commands below.

| Command | Description |
|---|---|
| `image_gaussian()` | Selects and executes the Gaussian filter to smooth the image and reduce noise. |
| `image_sobel()` | Selects and executes the Sobel filter to detect image edges and boundaries. |
| `image_laplacian()` | Selects and executes the Laplacian filter to highlight rapid changes in image intensity. |
| `image_canny()` | Selects and executes the Canny filter for detailed edge detection. |
| `image_all()` | Executes all four image-processing operations in the predefined sequence. |

### 4.2 Video Commands (Stored Video and Live Camera)

First select the source with `input_video("sample_video.mp4")` for a saved video or `input_video("live_video")` for the live USB camera, then run one of the commands below.

| Command | Description |
|---|---|
| `input_video("sample_video.mp4")` | Selects a stored video file as the input. |
| `input_video("live_video")` | Selects the live USB camera as the input. |
| `video_gaussian()` | Applies the Gaussian filter to every frame of the video. |
| `video_sobel()` | Applies the Sobel filter to every frame of the video. |
| `video_laplacian()` | Applies the Laplacian filter to every frame of the video. |
| `video_canny()` | Applies the Canny filter to every frame of the video. |
| `camera_view()` | Shows the camera picture alone, without any filter, to check the camera. |
| `set_camera_flip()` | Corrects an inverted camera picture (default is a 180° rotation). |
| `profile()` | Measures the input-decoding part and the FPGA + JPEG part separately to show what limits the frame rate. |

### 4.3 Filter Selection Through AXI GPIO

The software sends the necessary control signals through AXI GPIO, and the FPGA performs the selected operation. The same GPIO value is used for the image command and its video counterpart. The GPIO register is cleared to `0b0000` at start-up and after every run, so no filter path is enabled while the system is idle.

| Filter | Image Command | Video Command | `gpio_io_o[3:0]` | Output DMA (S2MM) |
|---|---|---|---|---|
| Gaussian | `image_gaussian()` | `video_gaussian()` | `0b0001` (bit 0) | `axi_dma_4` |
| Sobel | `image_sobel()` | `video_sobel()` | `0b0010` (bit 1) | `axi_dma_1` |
| Laplacian | `image_laplacian()` | `video_laplacian()` | `0b0100` (bit 2) | `axi_dma_2` |
| Canny | `image_canny()` | `video_canny()` | `0b1000` (bit 3) | `axi_dma_3` |
| All four | `image_all()` | — | `0b0001 → 0b0010 → 0b0100 → 0b1000` | all four in turn |

The processed image is then transferred back to DDR memory using DMA and displayed in the notebook (or on the web page for video).

## 5. System Block Diagram

```text
                  ┌────────────────────────┐
                  │       Input Image      │
                  └────────────┬───────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │   Image Preparation    │
                  │ Resize and Grayscale   │
                  │    256 × 256, 8-bit    │
                  └────────────┬───────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │   DDR Memory (Input)   │
                  └────────────┬───────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │    Input AXI DMA       │
                  │        MM2S            │
                  └────────────┬───────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │    AXI Broadcaster     │
                  └─────┬─────┬─────┬──────┘
                        │     │     │     │
             ┌──────────┘     │     │     └──────────┐
             ▼                ▼     ▼                ▼
       ┌──────────┐      ┌────────┐ ┌──────────┐ ┌──────────┐
       │ Gaussian │      │ Sobel  │ │Laplacian │ │  Canny   │
       │  Filter  │      │ Filter │ │  Filter  │ │  Filter  │
       └─────┬────┘      └───┬────┘ └────┬─────┘ └────┬─────┘
             └───────────────┴──────┬────┴────────────┘
                                    │
                                    ▼
                         ┌────────────────────────┐
                         │ Output Gate / Selection│
                         │    Controlled by GPIO  │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │    AXI Stream FIFO     │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │    Output AXI DMA      │
                         │         S2MM           │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │   DDR Memory (Output)  │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │    Python / Jupyter    │
                         │    Displayed Result    │
                         └────────────────────────┘

       Jupyter Notebook ──► AXI GPIO ──► Filter / Output Selection
```

### Complete Data Flow

**Input Image → Image Preparation → DDR Memory → Input DMA → AXI4-Stream → AXI Broadcaster → Selected Image Processing → Output Gate → FIFO → Output DMA → DDR Memory → Python → Displayed Result**

**For video:** the same flow is repeated for every frame. The frames come from a stored video file (decoded once with ffmpeg) or from the live USB camera, and the processed frames are shown on the board's web page (`http://<board-ip>:8000/`) and as a side-by-side preview in the notebook.

### Vivado Block Design

The implemented design uses one input DMA (`axi_dma_4`, MM2S and S2MM), three S2MM-only DMAs (`axi_dma_1`, `axi_dma_2`, `axi_dma_3`), two SmartConnect crossbars, the AXI4-Stream broadcaster, the Gaussian/Sobel, Laplacian and Canny cores, four GPIO-controlled output gates and four AXI4-Stream FIFOs. The five DMA master ports share the PS high-performance port `S_AXI_HP0`.

<img src="images/block-design.png" alt="Vivado block design" width="900">

*Figure: Vivado IP Integrator block design of the implemented system (redrawn from the hardware handoff file).*

<img src="images/data-path.png" alt="System data path" width="900">

*Figure: System data path, PS → PL streaming pipeline → PS, running in a single 120 MHz clock domain.*

<img src="images/filter-selection-datapath.png" alt="Filter selection datapath" width="900">

*Figure: Filter-selection datapath. Each of the four lanes keeps its own filter core running every cycle; the GPIO-driven Slice/gate pair only decides which lane's pixels continue to its FIFO and S2MM DMA.*

## 6. IP Cores Used

The system uses AXI-based IP cores and custom image-processing hardware to transfer image data, control the processing paths and return the processed image to memory.

| No. | IP Core / Hardware Block | Purpose |
|---:|---|---|
| 1 | Zynq7 Processing System | Provides the ARM processor, DDR memory access and Processing System interfaces. |
| 2 | AXI DMA (4 instances) | Transfers image data between DDR memory and FPGA processing hardware: `axi_dma_4` (MM2S and S2MM) and `axi_dma_1`, `axi_dma_2`, `axi_dma_3` (S2MM only). |
| 3 | AXI4-Stream Broadcaster | Distributes the input pixel stream to the available processing paths. |
| 4 | Gaussian Filter IP | Smooths the image and reduces noise. |
| 5 | Sobel Filter IP | Detects image edges and boundaries. |
| 6 | Laplacian Filter IP | Highlights rapid changes in image intensity. |
| 7 | Canny Filter IP | Performs detailed edge detection. |
| 8 | AXI GPIO | Transfers software filter-selection and control signals (4-bit register, bit-sliced by Slice blocks). |
| 9 | AXI4-Stream FIFO | Temporarily buffers the processed pixel stream. |
| 10 | Output Selection / Gating Logic (`axis_output_gate`) | Selects the processing result that continues to the output path. |
| 11 | AXI SmartConnect (2 instances) | Connects AXI master and slave interfaces: one for PS → DMA control and GPIO, one for the five DMA master ports → `S_AXI_HP0`. |
| 12 | Processor System Reset | Provides synchronised reset signals for the Processing System and Programmable Logic. |
| 13 | Constant IP | Fixed logic-level source that drives the `dcm_locked` input of the processor system reset block. |

### Register Addresses (64 KB each)

| Block | Address |
|---|---|
| `axi_dma_1` | `0x40400000` |
| `axi_dma_2` | `0x40410000` |
| `axi_dma_3` | `0x40420000` |
| `axi_dma_4` | `0x40430000` |
| AXI GPIO | `0x41200000` |

## 7. Results

The system supports four image-processing operations: Gaussian, Sobel, Laplacian and Canny. The input image is prepared in grayscale format, processed by the selected FPGA hardware path and displayed through Jupyter Notebook. The same four operations are also applied to stored video and live camera frames.

### 7.1 Input Image

![Input Image](images/input-image.png)

*Figure 2: Input image supplied to the image-processing system.*

### 7.2 Gaussian Filter Output

![Gaussian Filter Output](images/gaussian-output.png)

*Figure 3: Gaussian filter output showing image smoothing and noise reduction.*

### 7.3 Sobel Filter Output

![Sobel Filter Output](images/sobel-output.png)

*Figure 4: Sobel filter output highlighting image edges and boundaries.*

### 7.4 Laplacian Filter Output

![Laplacian Filter Output](images/laplacian-output.png)

*Figure 5: Laplacian filter output highlighting rapid changes in image intensity.*

### 7.5 Canny Filter Output

![Canny Filter Output](images/canny-output.png)

*Figure 6: Canny filter output showing detected edges.*

### 7.6 Video Processing Results

#### Saved Video Processing

A saved video is selected with `input_video("sample_video.mp4")` and processed with `video_gaussian()`, `video_sobel()`, `video_laplacian()` or `video_canny()`. The figures show a stored test frame (a blue ellipse, a yellow rectangle, a green triangle and white lines on a gradient background) together with the processed frame for each command.

![Saved Video - Gaussian](images/video-gaussian-output.png)

*Figure 7: Saved video, `video_gaussian()` output.*

![Saved Video - Sobel](images/video-sobel-output.png)

*Figure 8: Saved video, `video_sobel()` output.*

![Saved Video - Laplacian](images/video-laplacian-output.png)

*Figure 9: Saved video, `video_laplacian()` output.*

![Saved Video - Canny](images/video-canny-output.png)

*Figure 10: Saved video, `video_canny()` output.*

**Observation:** The Gaussian output keeps the shapes as smooth grey regions with softened boundaries; the Sobel output draws every boundary as a thick bright band; the Laplacian output shows thin double-line edges on a mid-grey background; and the Canny output gives thin, single-pixel-wide binary edges. Because the frame has hard, noise-free boundaries, all three edge maps are clean.

#### Live Camera Processing

The live camera is selected with `input_video("live_video")`. A USB camera is plugged into the USB host port of the PYNQ-Z2 board and is found automatically by the notebook; the micro-USB (PROG UART) cable powers the board and gives the connection to the computer, and an HDMI cable is also fitted. No additional hardware is needed, because the camera frames are processed by the same filter cores as the image and the saved video.

![Live Camera Setup](images/live-camera-setup.png)

*Figure 11: Experimental setup for live video processing: PYNQ-Z2 board with the USB camera connected to its USB host port.*

![Live Camera - Gaussian](images/live-gaussian-output.png)

*Figure 12: Live camera, `video_gaussian()` output.*

![Live Camera - Sobel](images/live-sobel-output.png)

*Figure 13: Live camera, `video_sobel()` output.*

![Live Camera - Laplacian](images/live-laplacian-output.png)

*Figure 14: Live camera, `video_laplacian()` output.*

![Live Camera - Canny](images/live-canny-output.png)

*Figure 15: Live camera, `video_canny()` output.*

**Observation:** For the live frame (a ceiling air-vent grille with nested rectangular louvres), the Gaussian output is a smoothed grey version of the camera picture; the Sobel output is brightest on the sharp edges of the louvres, while the soft shading gives only a weak response; the Laplacian output shows thin lines along the louvre edges on a mid-grey background; and the Canny output gives sparse binary lines that trace the louvre frames. The output page showed a live stream rate of **19.9 FPS** for the Laplacian filter. The processed live picture follows the camera without visible delay, because late frames are dropped and the newest frame is always processed.

### 7.7 FPGA Implementation Results

The project report records the following implementation and timing results (Vivado 2024.2, xc7z020clg400-1, 120 MHz PL clock).

| Parameter | Reported Result |
|---|---:|
| Worst Negative Slack (WNS) | +0.023 ns |
| Total Negative Slack (TNS) | 0 ns |
| Worst Hold Slack (WHS) | +0.012 ns |
| Total Hold Slack (THS) | 0 ns |
| Worst Pulse Width Slack (WPWS) | 2.916 ns |
| Failing Timing Endpoints | 0 out of 114,498 setup/hold and 38,827 pulse-width endpoints |
| Look-Up Tables (LUTs) | 18,987 / 53,200 (35.7%) |
| Flip-Flops | 36,550 / 106,400 (34.4%) |
| Block RAM (BRAM) | 15 / 140 (10.7%) |
| DSP Slices | 0 |
| Estimated On-Chip Power | 1.798 W (dynamic 1.657 W, static 0.141 W) |
| Junction Temperature | 45.7 °C |
| Thermal Margin | 39.3 °C |

<img src="images/resource-utilisation.png" alt="Resource utilisation" width="800">

*Figure: Post-implementation resource utilisation of the xc7z020 device.*

<img src="images/timing-slack.png" alt="Timing slack" width="800">

*Figure: Worst setup, hold and pulse-width slack after implementation.*

<img src="images/power-breakdown.png" alt="Power breakdown" width="800">

*Figure: On-chip power, static and dynamic share and dynamic breakdown.*

No DSP slices are needed because the kernel weights are powers of two (shift-and-add arithmetic). Less than 36 % of any logic resource is used, so about two thirds of the LUTs and flip-flops remain free for further filters.

#### Streaming Throughput

| Parameter | Value |
|---|---|
| PL clock | 120.0 MHz (period 8.33 ns) |
| Pixels per clock | 1 |
| Clock cycles per frame (256 × 256) | 65,536 |
| Time per frame in the PL | 546.1 µs |
| Theoretical maximum rate (PL only) | 1,831 FPS |
| Pixel throughput | 120.0 Mpixel/s |
| Required for 30 FPS | 1.97 Mpixel/s (1.64 % of PL capacity) |

The FPGA can process about sixty times the 30 FPS of the camera, so the PL is never the bottleneck of the video path. The delivered frame rate is set by the software work done for every frame (camera read, resizing, grayscale conversion, JPEG encoding and web serving).

### 7.8 Result Observations

- **Gaussian:** Reduces speckle noise and smooths the image.
- **Sobel:** Highlights edges and boundaries, although some texture noise may remain.
- **Laplacian:** Highlights rapid intensity changes and boundaries, with some residual texture noise.
- **Canny:** Produces cleaner, thinner and more continuous edges using non-maximum suppression, double thresholding and hysteresis. The implementation described in the project report uses a local-neighbourhood approximation for hysteresis.
- **Video:** The same four filters work on every frame of a stored video and of the live USB camera with no hardware change; the live output follows the camera without visible delay.

### 7.9 Comparison of Image, Stored Video and Live Video

All three modes use the same programmable-logic design, so the resource use, timing and power above are identical for all of them. What differs is the software around the hardware.

| Parameter | Image | Stored Video | Live Video |
|---|---|---|---|
| Source of the frame | PNG/JPG file, resized to 256 × 256 | Video file; ffmpeg decodes it once, frames cached in RAM | USB camera, MJPG 640 × 480 at 30 FPS, resized per frame |
| Frames per run | 1 (`image_all()`: 4 passes) | N (every frame of the file) | Continuous; oldest frame dropped when late |
| PL time per frame at 120 MHz | 546.1 µs (`image_all()`: 2.18 ms) | 546.1 µs | 546.1 µs |
| Frame rate delivered | Single frame | 24–30 FPS (source rate) | 19.9 FPS (measured, Laplacian) |
| PL load at delivered rate | — | 1.64 % at 30 FPS | 1.09 % at 19.9 FPS |
| Software memory | 704 KB (`image_all()`: 2.06 MB) | 1.13 MB + 192 KB per cached frame (about 151 MB with the full 150 MB cache) | 2.01 MB (constant) |
| Contiguous DMA memory (of 128 MB CMA) | 128 KB (`image_all()`: 320 KB) | 128 KB | 128 KB |
| Stage that limits the rate | Python and Matplotlib display | Source frame rate; Python JPEG encoding | Camera read, resizing and JPEG encoding in Python |
| Extra hardware needed | None | None | None |

<img src="images/mode-comparison.png" alt="Memory and data rate comparison" width="900">

*Figure: Comparison of the software memory (left, logarithmic scale) and the average data rates per path (right) for image, stored-video and live-video processing.*

The 150 MB frame cache holds 800 frames, i.e. 33.3 s of video at 24 FPS, 26.7 s at 30 FPS and 13.3 s at 60 FPS.

## 8. Example Operation

For example, if the user wants to perform Sobel processing, the user provides the input image and executes `image_sobel()` in Jupyter Notebook. The software sends the required filter-selection information (`0b0010`) through AXI GPIO.

The input DMA transfers the image from DDR memory to the FPGA. The selected Sobel processing path processes the pixel stream. The output gate and FIFO pass the result to the output DMA, which transfers it back to DDR memory. Python then displays the processed image.

```python
%run predefined.py.ipynb

input_image("input_image.png")
image_sobel()
```

The same overall process is used for Gaussian, Laplacian and Canny processing. The user can execute `image_all()` to run all four filters in the predefined sequence.

### Example: Video Processing

```python
# Stored video
input_video("sample_video.mp4")
video_canny()

# Live USB camera
input_video("live_video")
video_laplacian()
```

Open `http://<board-ip>:8000/` in a browser to see the processed video at full screen (double click toggles full-screen mode). A side-by-side input/output preview is also shown in the notebook.

### Sequence of Events for One Filter Run

| Step | Where | What happens |
|---:|---|---|
| 1 | Notebook (PS) | Overlay loaded; image resized to 256 × 256 and converted to 8-bit grayscale |
| 2 | Notebook (PS) | Contiguous DDR buffer allocated; a command such as `image_sobel()` writes the selection (`0b0010`) to AXI GPIO |
| 3 | PS → PL (AXI4-Lite) | DMA control registers receive source address, length and run bit; the receive channel of the selected filter's DMA is armed first, then the send channel of the input DMA |
| 4 | Input DMA (MM2S) | Image read from DDR3 in bursts and sent as a one-pixel-per-clock AXI4-Stream |
| 5 | Broadcaster, cores | Stream copied to the cores; each builds its 3×3 window and produces one result pixel per clock |
| 6 | Gates, FIFOs | Only the lane enabled by the GPIO bit passes its stream, buffered by a FIFO |
| 7 | Selected filter's DMA (S2MM) | Selected stream written back to an output buffer in DDR3 |
| 8 | Notebook (PS) | Python waits for both DMA transfers, invalidates the cache, reads the buffer as a NumPy array, displays it and clears the GPIO register |

## 9. Key Features

- Four image-processing operations: Gaussian, Sobel, Laplacian and Canny.
- Software-controlled filter selection through Jupyter Notebook.
- FPGA-based image processing on the PYNQ-Z2 board.
- **One design for images, stored video and live USB camera**: the same filter cores serve all three inputs.
- **Real-time streaming hardware**: one pixel per clock, 546.1 µs per 256 × 256 frame, up to 1,831 frames per second in the PL.
- **Timing closed at 120 MHz** with positive slack and no failing endpoints.
- **Compact and low-power**: 35.7 % LUTs, 34.4 % flip-flops, 10.7 % BRAM, no DSP slices, 1.798 W total on-chip power.
- AXI DMA for efficient image-data transfer.
- AXI4-Stream for continuous pixel-data transfer.
- AXI GPIO for filter and output selection.
- Python interface for controlling the system and displaying results.
- **Convenient video output**: the processed video is shown on a full-screen web page served by the board, with a side-by-side input/output preview in the notebook.
- Local image and video processing without requiring an internet connection for the processing operation.
- **Room to grow**: more than 60 % of the logic is still free, so further filter cores can be added next to the existing four.

## 10. Applications

Our system may be useful in the following applications:

- Defence and surveillance systems (including border surveillance).
- Video surveillance and monitoring: filtering and edge detection of video from cameras, drones or satellites, frame by frame, on the board at the site of use.
- Remote monitoring and disaster response.
- Image processing in locations with limited internet connectivity.
- Satellite, UAV and drone imaging, geographical mapping and infrastructure monitoring.
- Edge detection and image preprocessing for computer-vision systems.
- Education and research: a simple Jupyter-based platform for experimenting with FPGA image processing and comparing filters without rebuilding the hardware.

These are potential application areas and do not imply that the project has been deployed in each application.

## 11. Conclusion

Our project demonstrates a software-controlled FPGA-based multi-image-processing system using the PYNQ-Z2 platform. The user provides an input image and selects the required operation through Jupyter Notebook. Python handles software control, AXI GPIO provides filter selection, DMA transfers image data, AXI4-Stream carries the pixel stream, and the FPGA performs the selected image-processing operation.

The processed result is transferred back to memory and displayed in the notebook. The same system also processes stored video and live USB-camera video: since a video is a sequence of frames, each frame is passed through the same filter cores, so the hardware needed no change to extend from images to video. The FPGA is never the bottleneck of the video path, and the live output follows the camera without visible delay at 19.9 FPS.

The main concept of our project is to support multiple image-processing operations with software-based filter selection, efficient FPGA hardware processing and local operation without requiring internet connectivity.

### Future Scope

- Edge maps in a threshold-based land-cover classifier (water, urban, agricultural, forest, bare land) and frame-to-frame change detection for newly appeared roads or structures.
- Real-time satellite-feed or HDMI-input integration in place of user-supplied images (a USB camera is already supported).
- Use of information across frames (such as motion detection and frame differencing) on top of the per-frame filters, and higher-rate camera or HDMI inputs.
- Additional filter cores such as Prewitt, Scharr and bilateral filtering, and object or feature detection on the edge maps.
- A compact CNN accelerator behind the filter front end.
- Moving the JPEG encoding and colour conversion out of Python to raise the video frame rate.
- A multi-pixel-per-clock datapath for higher-resolution imagery, and onboard deployment on UAVs and small satellites.

## 12. References

1. Xilinx/AMD, *Zynq-7000 SoC Technical Reference Manual*.
2. Xilinx/AMD, *AXI DMA Product Guide*.
3. PYNQ Project Documentation, *PYNQ-Z2 and Python/Jupyter-Based FPGA Development*.
4. John Canny, “A Computational Approach to Edge Detection,” *IEEE Transactions on Pattern Analysis and Machine Intelligence*, 1986.

---

## 13. Project Team and Academic Details

1. **Pravin Bhangare**
2. **Harshada Dalvi**
3. **Swayam Sawant**
4. **Vaishnavi Bauchkar**

**Project Guide:** Prof. Satendra Mane

**Department:** Electronics and Telecommunication Engineering

**Institute:** Vidyalankar Institute of Technology, Mumbai

**Academic Year:** 2026–2027

