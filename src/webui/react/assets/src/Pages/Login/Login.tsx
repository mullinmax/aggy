import React, { useState } from "react";
import "./Login.scss";
import LoginForm from "../../Components/Form/LoginForm";
import SignUpForm from "../../Components/Form/SignUpForm";

export default function Login() {
  const [signUp, setSignUp] = useState(false);

  function signingUp() {
    setSignUp(true);
  }

  function loggingIn() {
    setSignUp(false);
  }

  return (
    <div className="Login">
      <h1>Welcome to Blinder!</h1>
      {signUp ? (
        <div>
          <h3>Please sign up</h3>
          <SignUpForm />
          <h3>Already have an account?</h3>
          <button className="Login-Button" onClick={loggingIn}>
            Login
          </button>
        </div>
      ) : (
        <div>
          <h3>Please login</h3>
          <LoginForm />
          <h3>Don't have an account?</h3>
          <button className="Login-Button Sign-Up-Button" onClick={signingUp}>
            Sign Up Here!
          </button>
        </div>
      )}
    </div>
  );
}
