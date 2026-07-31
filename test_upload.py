from src.upload.youtube import YouTubeUploader

uploader = YouTubeUploader()

video_id = uploader.upload_video(
    video_path="output/videos/run_20260608_100134_927d59.mp4",
    thumbnail_path="output/thumbnails/run_20260608_100134_927d59_thumb.jpg",
    title="YT Shorts Bot Upload Test",
    description="Testing automated upload pipeline.",
    tags=["test", "automation", "shorts"],
    privacy="private"
)

print("VIDEO ID:", video_id)