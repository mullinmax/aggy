const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");

module.exports = {
  entry: "./src/index.tsx",
  output: {
    filename: "bundle.js",
    path: path.resolve(__dirname, "dist"),
  },
  resolve: {
    extensions: [".tsx", ".ts", ".js"],
  },
  module: {
    rules: [
      {
        test: /\.(ts|tsx)$/,
        exclude: /node_modules/,
        use: "babel-loader",
      },
      {
        test: /\.(scss)$/,
        use: [
          {
            loader: "style-loader",
          },
          {
            loader: "css-loader",
          },
          {
            loader: "postcss-loader",
            options: {
              postcssOptions: {
                plugins: () => [require("autoprefixer")],
              },
            },
          },
          {
            loader: "sass-loader",
          },
        ],
      },
      {
        test: /\.(png|jpe?g|gif)$/i,
        type: "asset/resource",
        generator: {
          filename: "[name][ext]",
        },
      },
      {
        test: /\.svg$/i,
        issuer: { and: [/\.(js|ts|md)x?$/] },
        use: ["@svgr/webpack"],
      },
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: "./src/index.html",
    }),
  ],
  mode: "development",
  performance: {
    hints: false,
    maxEntrypointSize: 512000,
    maxAssetSize: 512000,
  },
  devServer: {
    allowedHosts: "all",
    /** "port"
     * port of dev server
     */
    port: "8080",
    /** "static"
     * This property tells Webpack what static file it should serve
     */
    static: ["./dist"],
    /** "open"
     * opens the browser after server is successfully started
     */
    // open: ["https://samhost.doze.dev"],
    // proxy: {
    //   "/auth": {
    //     target: "https://blinderapi.doze.dev",
    //     secure: false, // If your API server uses HTTPS, set this to true
    //     changeOrigin: true, // Needed for virtual hosted sites
    //     pathRewrite: { "^/auth": "" }, // Remove the /api prefix when forwarding requests
    //   },
    // },
    proxy: [
      {
        context: ["/"],
        target: "https://blinderapi.doze.dev",
        secure: true, // If your API server uses HTTPS, set this to true
        changeOrigin: true,
        // changeOrigin: true, // Needed for virtual hosted sites
      },
    ],
    headers: {
      "Access-Control-Allow-Origin": "*", // Allow all origins, adjust as needed
    },
    /** "hot"
     * enabling and disabling HMR. takes "true", "false" and "only".
     * "only" is used if enable Hot Module Replacement without page
     * refresh as a fallback in case of build failures
     */
    // hot: true,
    // /** "liveReload"
    //  * disable live reload on the browser. "hot" must be set to false for this to work
    //  */
    liveReload: true,
  },
};
