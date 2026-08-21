class DeepTutorResponse {
  constructor(data, httpResponse) {
    this.data = data;
    this.status = httpResponse ? httpResponse.statusCode() : 0;
  }

  json() {
    if (!this.data || this.data.length() === 0) return {};
    return NSJSONSerialization.JSONObjectWithDataOptions(this.data, 1);
  }
}

function deepTutorFetch(url, options) {
  options = options || {};
  var fullUrl = String(url || "").trim();
  if (fullUrl.indexOf("://") === -1) fullUrl = "https://" + fullUrl;

  var request = NSMutableURLRequest.requestWithURL(NSURL.URLWithString(fullUrl));
  request.setHTTPMethod(options.method || "GET");
  request.setTimeoutInterval(options.timeout || 30);
  request.setValueForHTTPHeaderField("application/json", "Content-Type");
  request.setValueForHTTPHeaderField("application/json", "Accept");
  if (options.authorization) {
    request.setValueForHTTPHeaderField(options.authorization, "Authorization");
  }
  if (options.json !== undefined) {
    request.setHTTPBody(
      NSJSONSerialization.dataWithJSONObjectOptions(options.json, 1)
    );
  }

  return new Promise(function(resolve, reject) {
    NSURLConnection.sendAsynchronousRequestQueueCompletionHandler(
      request,
      NSOperationQueue.mainQueue(),
      function(response, data, error) {
        if (error !== null && error !== undefined) {
          reject(error.localizedDescription());
          return;
        }
        resolve(new DeepTutorResponse(data, response));
      }
    );
  });
}
