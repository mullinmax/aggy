const path = require('path');
const HtmlWebpackPlugin = require("html-webpack-plugin");

module.exports = {
  entry: './src/index.tsx',
  output: {
    filename: 'bundle.js',
    path: path.resolve(__dirname, 'dist')
  },
  resolve: {
    extensions: ['.tsx', '.ts', '.js']
  },
  module: {
    rules: [
      {
        test: /\.(ts|tsx)$/,
        exclude: /node_modules/,
        use: 'babel-loader'
      }
    ]
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: './src/index.html'
    })
  ],
  mode: "development",
  performance: {
    hints: false,
    maxEntrypointSize: 512000,
    maxAssetSize: 512000,
  },
  devServer: {
    allowedHosts: 'all',
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
    open: true,
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

