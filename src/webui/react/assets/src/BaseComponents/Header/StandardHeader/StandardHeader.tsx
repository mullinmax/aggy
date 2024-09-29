import React, { useState } from "react";
import Nav from "../../../Components/Nav";
import AuthService from "../../../utils/auth";
import BlinderIconPng from "../../../Images/blinder-icon.png";
import BlinderIcon from "../../../Images/blinder-icon.svg";
import "./StandardHeader.scss";

// import Logo from ".";

interface HeaderProps {
  /** current page */
  currentPage: string;
  /** Sets current page state */
  setCurrentPage: Function;
  loggedIn: boolean;
}

export default function StandardHeader({
  currentPage,
  setCurrentPage,
  loggedIn,
}: HeaderProps) {
  function logoutHandler() {
    // const token = AuthService.getToken();
    AuthService.logout();
  }
  return (
    <div className="Header-Container">
      <div className="Header-Logo">
        <BlinderIcon />
      </div>
      {loggedIn ? (
        <div>
          <Nav currentPage={currentPage} setCurrentPage={setCurrentPage} />
          <h1>HEADER started</h1>
          <button onClick={logoutHandler}>Logout</button>
        </div>
      ) : (
        <div></div>
      )}
    </div>
  );
}
