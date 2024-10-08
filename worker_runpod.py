import os, json, requests, runpod

def download_file(url, save_dir='/content/ComfyUI/input'):
    os.makedirs(save_dir, exist_ok=True)
    file_name = url.split('/')[-1]
    file_path = os.path.join(save_dir, file_name)
    response = requests.get(url)
    response.raise_for_status()
    with open(file_path, 'wb') as file:
        file.write(response.content)
    return file_path

import torch
import shutil

import asyncio
import execution
import server

from comfy import model_management
from nodes import NODE_CLASS_MAPPINGS
from nodes import load_custom_node

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
server_instance = server.PromptServer(loop)
execution.PromptQueue(server)

load_custom_node("/content/ComfyUI/custom_nodes/ComfyUI-LivePortraitKJ")
load_custom_node("/content/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite")
load_custom_node("/content/ComfyUI/custom_nodes/ComfyUI-KJNodes")

DownloadAndLoadLivePortraitModels = NODE_CLASS_MAPPINGS["DownloadAndLoadLivePortraitModels"]()
LivePortraitLoadCropper = NODE_CLASS_MAPPINGS["LivePortraitLoadCropper"]()
LivePortraitCropper = NODE_CLASS_MAPPINGS["LivePortraitCropper"]()

LivePortraitProcess = NODE_CLASS_MAPPINGS["LivePortraitProcess"]()
LivePortraitComposite = NODE_CLASS_MAPPINGS["LivePortraitComposite"]()

VHS_LoadVideo = NODE_CLASS_MAPPINGS["VHS_LoadVideo"]()
VHS_VideoCombine = NODE_CLASS_MAPPINGS["VHS_VideoCombine"]()
ImageResizeKJ = NODE_CLASS_MAPPINGS["ImageResizeKJ"]()

with torch.inference_mode():
    pipeline = DownloadAndLoadLivePortraitModels.loadmodel(precision="fp16", mode="human")[0]

@torch.inference_mode()
def generate(input):
    values = input["input"]

    frame_load_cap = values['frame_load_cap']
    source_video_file = values['source_video_file']
    source_video_file = download_file(source_video_file)
    driving_video_file = values['driving_video_file']
    driving_video_file = download_file(driving_video_file)

    frame_load_cap = frame_load_cap
    source_video_file = source_video_file
    driving_video_file = driving_video_file
    force_rate = 0
    force_size = "Disabled"
    custom_width = 512
    custom_height = 512
    skip_first_frames = 0 
    select_every_nth = 1
    source_image = VHS_LoadVideo.load_video(video=source_video_file,
                                            force_rate=force_rate,
                                            force_size=force_size,
                                            custom_width=custom_width,
                                            custom_height=custom_height,
                                            frame_load_cap=frame_load_cap,
                                            skip_first_frames=skip_first_frames,
                                            select_every_nth=select_every_nth)
    source_fps = source_image[3]['source_fps']
    source_audio = source_image[2]
    source_image = source_image[0]

    driving_images = VHS_LoadVideo.load_video(video=driving_video_file,
                                            force_rate=force_rate,
                                            force_size=force_size,
                                            custom_width=custom_width,
                                            custom_height=custom_height,
                                            frame_load_cap=frame_load_cap,
                                            skip_first_frames=skip_first_frames,
                                            select_every_nth=select_every_nth)
    driving_fps = driving_images[3]['source_fps']
    driving_audio = driving_images[2]
    driving_images=driving_images[0]
    source_image = ImageResizeKJ.resize(source_image, 1024, 1024, True, "bilinear", 2)[0]
    cropper = LivePortraitLoadCropper.crop("CUDA", True, detection_threshold=0.5)[0]
    cropped_image, crop_info = LivePortraitCropper.process(pipeline, cropper, source_image, 512, 2.30, 0.0, -0.125, 0, "large-small", True)

    lip_zero=False
    lip_zero_threshold=0.03
    stitching=True
    relative_motion_mode="source_video_smoothed"
    driving_smooth_observation_variance=0.000003
    delta_multiplier=1.0
    mismatch_method="constant"
    opt_retargeting_info=None
    expression_friendly=False
    expression_friendly_multiplier=1.0
    cropped_image, liveportrait_out = LivePortraitProcess.process(source_image=source_image,
                                                                    driving_images=driving_images,
                                                                    crop_info=crop_info,
                                                                    pipeline=pipeline,
                                                                    lip_zero=lip_zero,
                                                                    lip_zero_threshold=lip_zero_threshold,
                                                                    stitching=stitching,
                                                                    relative_motion_mode=relative_motion_mode,
                                                                    driving_smooth_observation_variance=driving_smooth_observation_variance,
                                                                    delta_multiplier=delta_multiplier,
                                                                    mismatch_method=mismatch_method,
                                                                    opt_retargeting_info=opt_retargeting_info,
                                                                    expression_friendly=expression_friendly,
                                                                    expression_friendly_multiplier=expression_friendly_multiplier)

    full_images = LivePortraitComposite.process(source_image, cropped_image, liveportrait_out)[0]

    frame_rate=source_fps
    loop_count=0
    filename_prefix="LivePortrait"
    format="video/h264-mp4"
    pingpong=False
    audio=driving_audio
    combined_video = VHS_VideoCombine.combine_video( frame_rate=frame_rate,
                                    loop_count=loop_count,
                                    images=full_images,
                                    latents=None,
                                    filename_prefix=filename_prefix,
                                    format=format,
                                    pingpong=pingpong,
                                    save_output=True,
                                    prompt=None,
                                    extra_pnginfo=None,
                                    audio=audio,
                                    unique_id=None,
                                    manual_format_widgets=None,
                                    meta_batch=None,
                                    vae=None)

    source = combined_video["result"][0][1][1]
    source_with_audio = source.replace(".mp4", "-audio.mp4")
    source_with_png = source.replace(".mp4", ".png")
    destination = '/content/ComfyUI/output/LivePortrait.mp4'
    destination_with_audio = '/content/ComfyUI/output/LivePortrait-audio.mp4'
    destination_with_png = '/content/ComfyUI/output/LivePortrait.png'
    shutil.move(source, destination)
    shutil.move(source_with_audio, destination_with_audio)
    shutil.move(source_with_png, destination_with_png)
    
    result = destination_with_audio
    try:
        notify_uri = values['notify_uri']
        del values['notify_uri']
        notify_token = values['notify_token']
        del values['notify_token']
        discord_id = values['discord_id']
        del values['discord_id']
        if(discord_id == "discord_id"):
            discord_id = os.getenv('com_camenduru_discord_id')
        discord_channel = values['discord_channel']
        del values['discord_channel']
        if(discord_channel == "discord_channel"):
            discord_channel = os.getenv('com_camenduru_discord_channel')
        discord_token = values['discord_token']
        del values['discord_token']
        if(discord_token == "discord_token"):
            discord_token = os.getenv('com_camenduru_discord_token')
        job_id = values['job_id']
        del values['job_id']
        default_filename = os.path.basename(result)
        with open(result, "rb") as file:
            files = {default_filename: file.read()}
        payload = {"content": f"{json.dumps(values)} <@{discord_id}>"}
        response = requests.post(
            f"https://discord.com/api/v9/channels/{discord_channel}/messages",
            data=payload,
            headers={"Authorization": f"Bot {discord_token}"},
            files=files
        )
        response.raise_for_status()
        result_url = response.json()['attachments'][0]['url']
        notify_payload = {"jobId": job_id, "result": result_url, "status": "DONE"}
        web_notify_uri = os.getenv('com_camenduru_web_notify_uri')
        web_notify_token = os.getenv('com_camenduru_web_notify_token')
        if(notify_uri == "notify_uri"):
            requests.post(web_notify_uri, data=json.dumps(notify_payload), headers={'Content-Type': 'application/json', "Authorization": web_notify_token})
        else:
            requests.post(web_notify_uri, data=json.dumps(notify_payload), headers={'Content-Type': 'application/json', "Authorization": web_notify_token})
            requests.post(notify_uri, data=json.dumps(notify_payload), headers={'Content-Type': 'application/json', "Authorization": notify_token})
        return {"jobId": job_id, "result": result_url, "status": "DONE"}
    except Exception as e:
        error_payload = {"jobId": job_id, "status": "FAILED"}
        try:
            if(notify_uri == "notify_uri"):
                requests.post(web_notify_uri, data=json.dumps(error_payload), headers={'Content-Type': 'application/json', "Authorization": web_notify_token})
            else:
                requests.post(web_notify_uri, data=json.dumps(error_payload), headers={'Content-Type': 'application/json', "Authorization": web_notify_token})
                requests.post(notify_uri, data=json.dumps(error_payload), headers={'Content-Type': 'application/json', "Authorization": notify_token})
        except:
            pass
        return {"jobId": job_id, "result": f"FAILED: {str(e)}", "status": "FAILED"}
    finally:
        if os.path.exists(result):
            os.remove(result)

runpod.serverless.start({"handler": generate})