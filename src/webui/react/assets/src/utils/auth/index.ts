// use this to decode a token and get the user's information out of it

import { jwtDecode } from "jwt-decode";

// create a new class to instantiate for a user
class AuthService {
  // get user data
  getProfile() {
    return jwtDecode(this?.getToken());
  }

  // check if user's logged in
  loggedIn() {
    // Checks if there is a saved token and it's still valid
    const token = this.getToken();
    return !!token && !this.isTokenExpired(token); // handwaiving here
  }

  // check if token is expired
  isTokenExpired(token: string) {
    try {
      const decoded = jwtDecode(token);
      console.log(decoded.exp);
      if (decoded.exp < Date.now() / 1000) {
        return true;
      } else return false;
    } catch (err) {
      return false;
    }
  }

  getToken() {
    // Retrieves the user token from localStorage
    return localStorage.getItem("id_token");
  }

  login(idToken) {
    // Saves user token to localStorage
    localStorage.setItem("id_token", idToken);
    window.location.assign("/");
  }

  logout() {
    // Clear user token and profile data from localStorage
    localStorage.removeItem("id_token");
    // this will reload the page and reset the state of the application
    window.location.assign("/");
  }
}

export default new AuthService();

// // Function to get information from the token
// export const AuthService = (token: string) => {
//   function getTokenInfo(token: string) {
//     try {
//       const decoded = jwtDecode(token);
//       console.log(decoded); // Print the payload
//       return decoded;
//     } catch (error) {
//       console.error("Invalid token", error);
//       return null;
//     }
//   }
//   const tokenInfo = getTokenInfo(token);

//   isTokenExpired(tokenInfo) {
//     try {
//       const decoded = decode(token);
//       if (decoded.exp < Date.now() / 1000) {
//         return true;
//       } else return false;
//     } catch (err) {
//       return false;
//     }
//   }

//   // Example usage
//   // const token = "your.jwt.token.here";

//   console.log(tokenInfo);
// };

// // create a new class to instantiate for a user
// class AuthService {
//   // get user data
//   getProfile() {
//     return decode(this.getToken());
//   }

//   // check if user's logged in
//   loggedIn() {
//     // Checks if there is a saved token and it's still valid
//     const token = this.getToken();
//     return !!token && !this.isTokenExpired(token); // handwaiving here
//   }

//   // check if token is expired
// isTokenExpired(token) {
//   try {
//     const decoded = decode(token);
//     if (decoded.exp < Date.now() / 1000) {
//       return true;
//     } else return false;
//   } catch (err) {
//     return false;
//   }
// }

//   getToken() {
//     // Retrieves the user token from localStorage
//     return localStorage.getItem("id_token");
//   }

//   login(idToken) {
//     // Saves user token to localStorage
//     localStorage.setItem("id_token", idToken);
//     window.location.assign("/");
//   }

//   logout() {
//     // Clear user token and profile data from localStorage
//     localStorage.removeItem("id_token");
//     // this will reload the page and reset the state of the application
//     window.location.assign("/");
//   }
// };
