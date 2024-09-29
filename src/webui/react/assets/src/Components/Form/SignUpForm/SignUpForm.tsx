import React, { useState, useEffect } from "react";
// import { userLogin } from "../../../utils/userLogin";
import { createUser } from "../../../utils/createUser";
import AuthService from "../../../utils/auth";
import { userLogin } from "../../../utils/userLogin";
import "./SignUpForm.scss";
import "../LoginForm/LoginForm.scss";

export default function LoginForm() {
  const [userFormData, setUserFormData] = useState({
    username: "",
    password: "",
  });
  // const [validated] = useState(false);
  // const [showAlert, setShowAlert] = useState(false);

  const loggedIn = AuthService.loggedIn();

  const handleInputChange = (event: any) => {
    const { name, value } = event.target;
    setUserFormData({ ...userFormData, [name]: value });
  };

  const handleSignUp = async (event: any) => {
    event.preventDefault();
    const response = await createUser(userFormData);
    try {
      console.log(response);
      if (!response.ok) {
        console.log("no response?");
        // console.log(response);
      }
      userLogin(userFormData)
        .then((response) => {
          if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
          }
          return response.json();
        })
        .then((data) => {
          console.log("Login successful:", data);
          // Store the token or session ID if needed
          const token = data.access_token; // Example: adjust based on actual API response
          // Store token in local storage, session storage, or in-memory
          AuthService.login(token);
          // AuthService(token);
        })
        .catch((error) => {
          console.error("Login failed:", error);
        });
    } catch {
      alert(response.statusText);
    }
  };

  return (
    <div>
      {loggedIn === false ? (
        <div className="Login-Form-Container">
          <label htmlFor="username" className="Login-Form-Label">
            Username
          </label>
          <input
            type="text"
            id="sign-up-username"
            className="Login-Form-Input"
            name="username"
            placeholder="Username"
            required
            onChange={handleInputChange}
          />
          <label htmlFor="password" className="Login-Form-Label">
            Password
          </label>
          <input
            type="password"
            id="sign-up-password"
            className="Login-Form-Input"
            name="password"
            placeholder="Password"
            required
            onChange={handleInputChange}
          />
          <button onClick={handleSignUp} className="Login-Form-Submit">
            Sign Up
          </button>
        </div>
      ) : null}
    </div>
  );
}
