package com.nep.user.service;

import com.nep.common.page.PageResult;
import com.nep.user.model.dto.UserQuery;
import com.nep.user.model.enums.UserStatus;
import com.nep.user.model.vo.UserVO;

public interface UserService {
    /**
     * 创建用户
     * 
     * @param username 用户名
     * @param password 密码
     * @param nickname 昵称
     * @return 创建后的用户
     */
    UserVO createUser(String username, String password, String nickname);

    /**
     * 查询用户列表
     * 
     * @param query 查询参数
     * @return 用户列表
     */
    PageResult<UserVO> listUsers(UserQuery query);

    /**
     * 更新用户昵称
     * 
     * @param userId   用户ID
     * @param nickname 昵称
     */
    void updateUserNickname(Long userId, String nickname);

    /**
     * 更新用户状态
     * 
     * @param userId 用户ID
     * @param status 状态
     */
    void updateUserStatus(Long userId, UserStatus status);

    /**
     * 重置用户密码
     * 
     * @param userId      用户ID
     * @param newPassword 新密码
     */
    void resetUserPassword(Long userId, String newPassword);

}
