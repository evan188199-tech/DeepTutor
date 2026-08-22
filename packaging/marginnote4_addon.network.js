function deepTutorFetch(url, options) {
  options = options || {};
  var fullUrl = String(url || "").trim();
  if (fullUrl.indexOf("://") === -1) fullUrl = "https://" + fullUrl;
  var headers = {};
  var key;

  if (options.authorization) {
    headers.Authorization = options.authorization;
  }
  if (options.headers) {
    for (key in options.headers) {
      if (Object.prototype.hasOwnProperty.call(options.headers, key)) {
        headers[key] = options.headers[key];
      }
    }
  }

  return MNConnection.fetchDev(fullUrl, {
    method: options.method || "GET",
    timeout: options.timeout || 30,
    headers: headers,
    json: options.json
  }).then(function(response) {
    if (!response) throw "network request failed";
    return response;
  });
}
