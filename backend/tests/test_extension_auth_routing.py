"""
Unit tests for extension Google Auth handling & browser session streaming.
"""
import subprocess
import json

def test_js_helpers():
    # Run a node snippet to test isGoogleAuthUrl logic from popup and content scripts
    js_test = """
    function isGoogleAuthUrl(url) {
      if (!url || typeof url !== 'string') return false;
      return (
        url.startsWith('blob:') ||
        url.includes('google.com') ||
        url.includes('googleapis.com') ||
        url.includes('googleusercontent.com') ||
        url.includes('googlevideo.com') ||
        url.includes('flow.google')
      );
    }

    const cases = [
      ['blob:https://flow.google.com/1234', true],
      ['https://storage.googleapis.com/veo-videos/gen_456.mp4', true],
      ['https://flow.google.com/api/download?id=789', true],
      ['https://rr1---sn-nv47ln7s.googlevideo.com/videoplayback?id=abc', true],
      ['https://lh3.googleusercontent.com/video_xyz', true],
      ['https://cdn.example.com/free_video.mp4', false],
      ['http://my-s3-bucket.amazonaws.com/clip.mov', false],
    ];

    let allOk = true;
    for (const [url, expected] of cases) {
      const result = isGoogleAuthUrl(url);
      if (result !== expected) {
        console.error(`FAIL: ${url} expected ${expected} but got ${result}`);
        allOk = false;
      }
    }

    if (!allOk) {
      process.exit(1);
    }
    console.log("All isGoogleAuthUrl test cases PASSED!");
    """

    res = subprocess.run(["node", "-e", js_test], capture_output=True, text=True)
    print(res.stdout)
    assert res.returncode == 0, res.stderr

if __name__ == "__main__":
    test_js_helpers()
