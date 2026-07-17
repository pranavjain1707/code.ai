import os
import uuid
import logging
import urllib.parse
import asyncio
import random
import httpx

logger = logging.getLogger(__name__)

class ImageGeneratorService:
    def __init__(self):
        self.output_dir = "app/static/generated"
        self.base_url = "https://image.pollinations.ai/prompt"

    async def generate_and_save_image(self, prompt: str) -> str:
        """
        Generates an image from a text prompt via Pollinations AI.
        Saves the image locally and returns the local static path.
        Falls back to the direct Pollinations URL on failure.
        """
        encoded_prompt = urllib.parse.quote(prompt.strip())
        
        # Clean up any existing 0-byte files in the generated folder to fix past broken images
        try:
            if os.path.exists(self.output_dir):
                for f in os.listdir(self.output_dir):
                    fpath = os.path.join(self.output_dir, f)
                    if os.path.isfile(fpath) and os.path.getsize(fpath) == 0:
                        os.remove(fpath)
                        logger.info(f"Removed old 0-byte file: {fpath}")
        except Exception as e:
            logger.warning(f"Error cleaning up old 0-byte files: {e}")

        # Attempt generation twice with different seeds
        for attempt in range(2):
            seed = random.randint(0, 999999)
            pollinations_url = f"{self.base_url}/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={seed}"
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            
            try:
                logger.info(f"Requesting image generation for prompt: '{prompt}' (attempt {attempt+1}, seed {seed})")
                os.makedirs(self.output_dir, exist_ok=True)
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(pollinations_url, headers=headers, follow_redirects=True)
                    
                    if response.status_code == 200 and len(response.content) > 0:
                        filename = f"{uuid.uuid4()}.png"
                        filepath = os.path.join(self.output_dir, filename)
                        
                        # Save the image bytes asynchronously
                        def save_bytes():
                            with open(filepath, "wb") as f:
                                f.write(response.content)
                                
                        await asyncio.to_thread(save_bytes)
                        logger.info(f"Image successfully saved locally to {filepath} ({len(response.content)} bytes)")
                        return f"/static/generated/{filename}"
                    else:
                        logger.warning(
                            f"Pollinations AI returned status {response.status_code} "
                            f"and {len(response.content)} bytes on attempt {attempt+1}."
                        )
            except Exception as e:
                logger.error(f"Error generating or saving image locally on attempt {attempt+1}: {e}")
            
            # Wait briefly before retry
            if attempt == 0:
                await asyncio.sleep(0.5)

        # Fallback to direct URL if all cache-bypassed fetch attempts fail
        fallback_seed = random.randint(0, 999999)
        return f"{self.base_url}/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={fallback_seed}"

image_generator = ImageGeneratorService()
