# snswebsite
Static website for Scotch'n'Soda Theatre

## Current Branches

### master
The current static site at snstheatre.org
- Gallery photos now live in s3://sns-photos-static/images/ and are served
from static.snstheatre.org. galleries/images/ is no longer tracked, so don't upload images there. Gallery pages and all_galleries.html point at the S3 URLs.

### style-edits
- (merged) restructured Get Involved / Subtroupe pages, most information is now on About with only meeting times in Get Involved

### roles-documentation
- (merged) start to documentation page, accessible through Get Invovled
- planning on condensing / adding content for actors and pit

## Other Notes
- When editing: sometimes a page will look the same even after editing. If this happens, clear the browser cache and reload the site and the updates will show up.
